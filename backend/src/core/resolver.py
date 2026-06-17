# src/core/resolver.py
import logging
import os
import re
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)


class Resolver:
    """
    Connects to datasources and runs SQL queries
    to fetch real values for placeholders.
    Supports batching — one connection per datasource.
    Supports dataset resolution — fetch multiple rows for table repeat.
    Supports format_json — date/currency/number/string formatting.
    Supports runtime_params injection into SQL — {{customer_id}} → 'C1001'
    """

    def __init__(self, ds_url: Optional[str] = None):
        self.default_ds_url = ds_url or os.getenv(
            "KASETTI_DS_URL",
            "postgresql://eivsdemo:eivsdemo@kasetti-db:5432/kasetti_bank"
        )

    # -----------------------------------------------------------------
    # ★ NEW: Inject runtime_params into SQL
    # -----------------------------------------------------------------

    def inject_params(self, sql_text: str, runtime_params: Dict[str, Any]) -> str:
        """
        Replace {{param_name}} inside SQL with actual runtime values.

        Example:
            sql_text = "SELECT name FROM customers WHERE customer_id = '{{customer_id}}'"
            runtime_params = {"customer_id": "C1002"}
            result = "SELECT name FROM customers WHERE customer_id = 'C1002'"

        Rules:
        - Only replaces {{param}} tokens that exist in runtime_params
        - Escapes single quotes to prevent SQL injection
        - Leaves unreplaced tokens as-is (they stay as {{param}})
        """
        if not sql_text or not runtime_params:
            return sql_text

        result = sql_text
        for key, value in runtime_params.items():
            # Escape single quotes to prevent SQL injection
            safe_value = str(value).replace("'", "''")
            # Replace {{key}} with the value
            result = result.replace(f"{{{{{key}}}}}", safe_value)

        # Log if any tokens were injected
        if result != sql_text:
            logger.info(f"SQL param injection: {sql_text!r} → {result!r}")

        return result

    # -----------------------------------------------------------------
    # format_json application
    # -----------------------------------------------------------------

    def apply_format(self, value: str, format_json: Optional[Dict]) -> str:
        """
        Apply format_json spec to a resolved value.

        Supported format types:
          currency: { "type": "currency", "symbol": "₹", "decimals": 2 }
          date:     { "type": "date", "format": "DD-MMM-YYYY" }
          number:   { "type": "number", "decimals": 2, "suffix": "% per annum" }
          string:   { "type": "string", "ops": ["uppercase"|"lowercase"|"trim"] }
        """
        if not format_json or not value:
            return value

        fmt_type = format_json.get("type", "")

        try:
            # ── Currency ──────────────────────────────────────────
            if fmt_type == "currency":
                symbol   = format_json.get("symbol", "₹")
                decimals = format_json.get("decimals", 2)
                num      = float(value.replace(",", ""))
                if symbol == "₹":
                    formatted = self._indian_number_format(num, decimals)
                else:
                    formatted = f"{num:,.{decimals}f}"
                result = f"{symbol}{formatted}"
                logger.info(f"Currency format: {value} → {result}")
                return result

            # ── Date ──────────────────────────────────────────────
            elif fmt_type == "date":
                from datetime import datetime
                fmt = format_json.get("format", "DD-MMM-YYYY")
                parsed = None
                for date_fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%d/%m/%Y", "%m/%d/%Y"]:
                    try:
                        parsed = datetime.strptime(str(value).split("+")[0].strip(), date_fmt)
                        break
                    except ValueError:
                        continue
                if parsed:
                    result = self._format_date(parsed, fmt)
                    logger.info(f"Date format: {value} → {result}")
                    return result
                return value

            # ── Number ────────────────────────────────────────────
            elif fmt_type == "number":
                decimals  = format_json.get("decimals", 2)
                prefix    = format_json.get("prefix", "")
                suffix    = format_json.get("suffix", "")
                num       = float(value.replace(",", ""))
                formatted = f"{num:,.{decimals}f}"
                result    = f"{prefix}{formatted}{suffix}"
                logger.info(f"Number format: {value} → {result}")
                return result

            # ── String ────────────────────────────────────────────
            elif fmt_type == "string":
                ops    = format_json.get("ops", [])
                result = value
                for op in ops:
                    if op == "uppercase":    result = result.upper()
                    elif op == "lowercase":  result = result.lower()
                    elif op == "trim":       result = result.strip()
                    elif op == "capitalize": result = result.capitalize()
                    elif op == "title":      result = result.title()
                logger.info(f"String format ({ops}): {value} → {result}")
                return result

        except Exception as exc:
            logger.warning(f"format_json failed for value '{value}': {exc}")

        return value

    def _indian_number_format(self, num: float, decimals: int) -> str:
        decimal_part = f"{num:.{decimals}f}".split(".")[1] if decimals > 0 else ""
        integer_part = int(num)
        s = str(integer_part)
        if len(s) <= 3:
            result = s
        else:
            result = s[-3:]
            s = s[:-3]
            while s:
                result = s[-2:] + "," + result
                s = s[:-2]
        return result + (f".{decimal_part}" if decimal_part else "")

    def _format_date(self, dt, fmt: str) -> str:
        month_abbr = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        month_full = ["January","February","March","April","May","June","July","August","September","October","November","December"]
        result = fmt
        result = result.replace("DD",   f"{dt.day:02d}")
        result = result.replace("D",    str(dt.day))
        result = result.replace("MMMM", month_full[dt.month - 1])
        result = result.replace("MMM",  month_abbr[dt.month - 1])
        result = result.replace("MM",   f"{dt.month:02d}")
        result = result.replace("YYYY", str(dt.year))
        result = result.replace("YY",   str(dt.year)[-2:])
        return result

    # -----------------------------------------------------------------
    # Single resolve (fallback)
    # -----------------------------------------------------------------

    async def resolve(self, name: str, sql_text: str, runtime_params: Optional[Dict[str, Any]] = None) -> str:
        """Run single SQL against default datasource."""
        if not sql_text or not sql_text.strip():
            return ""
        # Inject runtime_params into SQL
        injected_sql = self.inject_params(sql_text, runtime_params or {})
        try:
            conn = await asyncpg.connect(self.default_ds_url)
            try:
                row = await conn.fetchrow(injected_sql)
                if row:
                    value = list(row.values())[0]
                    return str(value) if value is not None else ""
                return ""
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning(f"Resolver failed for placeholder '{name}': {exc}")
            return ""

    # -----------------------------------------------------------------
    # ★ UPDATED: Batch resolve — inject runtime_params into SQL
    # -----------------------------------------------------------------

    async def resolve_batch(
        self,
        placeholders: List[Dict[str, Any]],
        ds_url: str,
        runtime_params: Optional[Dict[str, Any]] = None,   # ← NEW PARAM
    ) -> Dict[str, str]:
        """
        Resolve multiple placeholders in ONE connection.
        Injects runtime_params into SQL before running.
        Applies format_json after resolving each value.

        Example:
            placeholder SQL: SELECT name FROM customers WHERE customer_id = '{{customer_id}}'
            runtime_params:  {"customer_id": "C1002"}
            injected SQL:    SELECT name FROM customers WHERE customer_id = 'C1002'
            result:          {"customer_name": "Rajani"}
        """
        results: Dict[str, str] = {}
        if not placeholders:
            return results

        params = runtime_params or {}

        try:
            conn = await asyncpg.connect(ds_url)
            logger.info(f"Batch: opened 1 connection for {len(placeholders)} placeholders")
            try:
                for ph in placeholders:
                    name         = ph["name"]
                    sql_text     = ph.get("sql_text", "")
                    sample_value = ph.get("sample_value", "")
                    format_json  = ph.get("format_json") or {}

                    if not sql_text or not sql_text.strip():
                        results[name] = sample_value
                        continue

                    # ★ Inject runtime_params into SQL before running
                    injected_sql = self.inject_params(sql_text, params)

                    try:
                        row = await conn.fetchrow(injected_sql)
                        if row:
                            raw_value = list(row.values())[0]
                            raw_str   = str(raw_value) if raw_value is not None else sample_value
                            formatted = self.apply_format(raw_str, format_json)
                            results[name] = formatted
                            logger.info(f"Batch resolved '{name}': {raw_str} → {formatted}")
                        else:
                            results[name] = sample_value
                    except Exception as exc:
                        logger.warning(f"Batch SQL failed for '{name}': {exc}")
                        results[name] = sample_value
            finally:
                await conn.close()
                logger.info(f"Batch: closed connection after resolving {len(placeholders)} placeholders")

        except Exception as exc:
            logger.error(f"Batch connection failed: {exc}")
            for ph in placeholders:
                results[ph["name"]] = ph.get("sample_value", "")

        return results

    # -----------------------------------------------------------------
    # ★ UPDATED: Dataset resolve — inject runtime_params into repeat SQL
    # -----------------------------------------------------------------

    async def resolve_dataset(
        self,
        block_id: str,
        repeat_sql: str,
        ds_url: Optional[str] = None,
        runtime_params: Optional[Dict[str, Any]] = None,   # ← NEW PARAM
    ) -> List[List[str]]:
        """
        Run SQL that returns MULTIPLE rows for table repeat.
        Injects runtime_params into SQL before running.

        Example:
            repeat_sql:     SELECT * FROM transactions WHERE customer_id = '{{customer_id}}'
            runtime_params: {"customer_id": "C1002"}
            injected SQL:   SELECT * FROM transactions WHERE customer_id = 'C1002'
            result:         All transactions for Rajani
        """
        if not repeat_sql or not repeat_sql.strip():
            return []

        url = ds_url or self.default_ds_url

        # ★ Inject runtime_params into repeat SQL
        injected_sql = self.inject_params(repeat_sql, runtime_params or {})

        try:
            conn = await asyncpg.connect(url)
            try:
                rows = await conn.fetch(injected_sql)
                if not rows:
                    logger.info(f"Table repeat SQL returned 0 rows for block '{block_id}'")
                    return []

                result = []
                for row in rows:
                    result.append([
                        str(v) if v is not None else ""
                        for v in row.values()
                    ])

                logger.info(f"Table repeat resolved {len(result)} rows for block '{block_id}'")
                return result

            finally:
                await conn.close()

        except Exception as exc:
            logger.warning(f"Dataset resolve failed for block '{block_id}': {exc}")
            return []

    # -----------------------------------------------------------------
    # Test connection
    # -----------------------------------------------------------------

    async def test_connection(self) -> bool:
        try:
            conn = await asyncpg.connect(self.default_ds_url)
            await conn.fetchval("SELECT 1")
            await conn.close()
            return True
        except Exception as exc:
            logger.error(f"Datasource connection test failed: {exc}")
            return False