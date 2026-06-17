const FieldPalette = ({ onInsertField }) => {
  const [datasources, setDatasources] = useState([]);
  const [fields, setFields] = useState({});

  useEffect(() => {
    uiService.getDatasources().then(setDatasources);
  }, []);

  const loadFields = (datasourceId) => {
    uiService.getFields(datasourceId).then(setFields);
  };

  return (
    <div>
      {datasources.map((ds) => (
        <button key={ds.datasource_id} onClick={() => loadFields(ds.datasource_id)}>
          {ds.name}
        </button>
      ))}
      {Object.keys(fields).map((entity) => (
        <div key={entity}>
          <strong>{entity}</strong>
          {fields[entity].map((f) => (
            <div key={f.name} onClick={() => onInsertField(f.name)}>
              {f.name} ({f.type})
            </div>
          ))}
        </div>
      ))}
    </div>
  );
};
