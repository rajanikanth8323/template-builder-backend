const BlockCanvas = ({ layoutJson, onDrop }) => {
  const [blocks, setBlocks] = useState(layoutJson.blocks \vert \vert  []);

  const addBlock = (type) => {
    const newBlock = { id: uuid(), type, content: type === "text" ? "Edit text" : null, columns: type === "table" ? [] : null };
    setBlocks([...blocks, newBlock]);
  };

  return (
    <div onDragOver={(e) => e.preventDefault()} onDrop={(e) => onDrop(e)}>
      {blocks.map((b) => (
        <div key={b.id} draggable>
          {b.type === "text" && <TextBlock block={b} />}
          {b.type === "table" && <TableBlock block={b} />}
        </div>
      ))}
      <button onClick={() => addBlock("text")}>Add Text</button>
      <button onClick={() => addBlock("table")}>Add Table</button>
    </div>
  );
};
