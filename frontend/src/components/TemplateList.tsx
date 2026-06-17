const TemplateList = () => {
  const [templates, setTemplates] = useState([]);
  useEffect(() => {
    api.getTemplates().then(setTemplates);
  }, []);

  const createTemplate = () => {
    api.createTemplate({ name: "New Template", description: "", layout_json: { blocks: [] } }).then((id) => navigate(`/editor/${id}`));
  };

  const publishTemplate = (id) => {
    api.publishTemplate(id).then(() => load());
  };

  return (
    <div>
      <button onClick={createTemplate}>Create Template</button>
      {templates.map((t) => (
        <div key={t.template_id}>
          <span>{t.name}</span>
          <button onClick={() => navigate(`/editor/${t.template_id}`)}>Edit</button>
          <button onClick={() => publishTemplate(t.template_id)}>Publish</button>
        </div>
      ))}
    </div>
  );
};
