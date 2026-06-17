const PreviewPane = ({ templateId, locale, runtimeParams }) => {
  const [html, setHtml] = useState("");

  const refresh = () => {
    uiService.previewTemplate(templateId, locale, runtimeParams).then((res) => setHtml(res.preview_html));
  };

  return (
    <div>
      <button onClick={refresh}>Refresh Preview</button>
      <iframe srcDoc={html} />
    </div>
  );
};
