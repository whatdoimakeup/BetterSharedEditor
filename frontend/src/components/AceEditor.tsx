import AceEditor from "react-ace";
import * as Y from "yjs";

import "ace-builds/src-noconflict/mode-python";
import "ace-builds/src-noconflict/theme-dracula";
import "ace-builds/src-noconflict/ext-language_tools";
import { useEffect, useRef } from "react";
import type { Delta } from "ace-builds-internal/document";
import { editorStore } from "@/stores/rootStore";

interface AceEditorComponentProps {
  yText?: Y.Text;
}

function normalizeDeltaText(delta: Delta): string {
  return delta.lines.join("\n").replace(/\r\n/g, "\n");
}

const AceEditorComponent = ({
  yText = editorStore.yText,
}: AceEditorComponentProps) => {
  const editorRef = useRef<AceEditor | null>(null);
  const isSyncingRef = useRef(false);

  useEffect(() => {
    const editor = editorRef.current?.editor;
    if (!editor) return;

    const session = editor.getSession();
    const doc = session.getDocument();
    const initialValue = yText.toString();

    if (doc.getValue() !== initialValue) {
      editor.setValue(initialValue, -1);
    }

    const handleAceChange = (delta: Delta) => {
      if (isSyncingRef.current) return;

      const startIdx = doc.positionToIndex(delta.start);
      const deltaText = normalizeDeltaText(delta);

      yText.doc?.transact(() => {
        if (delta.action === "insert") {
          if (deltaText.length > 0) {
            yText.insert(startIdx, deltaText);
          }
        } else if (delta.action === "remove") {
          if (deltaText.length > 0) {
            yText.delete(startIdx, deltaText.length);
          }
        }
      }, "ace");
    };

    const handleYjsChange = (
      event: Y.YTextEvent,
      transaction: Y.Transaction,
    ) => {
      if (transaction.origin === "ace" || isSyncingRef.current) return;

      isSyncingRef.current = true;
      try {
        let pos = 0;

        for (const delta of event.delta) {
          if (delta.retain) {
            pos += delta.retain;
          } else if (delta.insert) {
            const acePos = doc.indexToPosition(pos, 0);
            const insertedText = delta.insert.toString();
            doc.insert(acePos, insertedText);
            pos += insertedText.length;
          } else if (delta.delete) {
            const start = doc.indexToPosition(pos, 0);
            const end = doc.indexToPosition(pos + delta.delete, 0);
            doc.remove({ start, end });
          }
        }
      } finally {
        isSyncingRef.current = false;
      }
    };

    doc.on("change", handleAceChange);
    yText.observe(handleYjsChange);

    return () => {
      doc.off("change", handleAceChange);
      yText.unobserve(handleYjsChange);
    };
  }, [yText]);

  return (
    <AceEditor
      ref={editorRef}
      mode="python"
      theme="dracula"
      name="shared-editor-ace"
      editorProps={{ $blockScrolling: true }}
      width="100%"
      height="100%"
      fontSize={20}
      setOptions={{ useWorker: false, enableLiveAutocompletion: true }}
    />
  );
};

export default AceEditorComponent;
