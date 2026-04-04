/**
 * Monaco Editor component with Yjs collaborative editing support.
 *
 * Integrates Monaco Editor with Yjs via y-monaco binding for
 * real-time collaborative editing with cursor awareness.
 */

import { useEffect, useRef, useState } from "react";
import { observer } from "mobx-react-lite";
import { editorStore } from "@/stores/rootStore";
import * as monaco from "monaco-editor";
import { MonacoBinding } from "y-monaco";

// Configure Monaco worker paths for Vite
import editorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import jsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";
import cssWorker from "monaco-editor/esm/vs/language/css/css.worker?worker";
import htmlWorker from "monaco-editor/esm/vs/language/html/html.worker?worker";
import tsWorker from "monaco-editor/esm/vs/language/typescript/ts.worker?worker";

self.MonacoEnvironment = {
  getWorker(_, label) {
    if (label === "json") return new jsonWorker();
    if (label === "css" || label === "scss" || label === "less")
      return new cssWorker();
    if (label === "html" || label === "handlebars" || label === "razor")
      return new htmlWorker();
    if (label === "typescript" || label === "javascript") return new tsWorker();
    return new editorWorker();
  },
};

interface MonacoEditorProps {
  roomId: number;
}

const MonacoEditor = observer(({ roomId }: MonacoEditorProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const bindingRef = useRef<MonacoBinding | null>(null);
  const [isReady, setIsReady] = useState(false);
  const provider = editorStore.provider;
  const yDoc = editorStore.yDoc;
  const yText = editorStore.yText;

  // Create Monaco editor when container is ready
  useEffect(() => {
    if (!containerRef.current) return;

    const editor = monaco.editor.create(containerRef.current, {
      value: "",
      language: "javascript",
      theme: "vs-dark",
      fontSize: 14,
      tabSize: 2,
      minimap: { enabled: false },
      automaticLayout: true,
      scrollBeyondLastLine: false,
      wordWrap: "on",
      renderWhitespace: "selection",
      bracketPairColorization: { enabled: true },
      guides: { bracketPairs: true, indentation: true },
    });

    editor.onDidChangeModelContent((e) => {
      console.log(
        "[Monaco] Model content changed, version:",
        e.versionId,
        "changes:",
        e.changes.length,
      );
    });

    editorRef.current = editor;
    setIsReady(true);

    return () => {
      editor.dispose();
    };
  }, []);

  // Create Yjs binding when editor and provider are ready
  useEffect(() => {
    if (!editorRef.current || !isReady) return;
    if (!provider) {
      console.log("[MonacoEditor] Waiting for provider...");
      return;
    }

    const editor = editorRef.current;
    const model = editor.getModel();
    if (!model) {
      console.error("[MonacoEditor] No model found!");
      return;
    }

    console.log(
      "[MonacoEditor] Creating MonacoBinding for room",
      roomId,
      "yText length:",
      yText.length,
      "yDoc clientID:",
      yDoc.clientID,
      "awareness:",
      !!provider.awareness,
    );

    // Log Yjs update events
    const yjsUpdateHandler = (update: Uint8Array, origin: any) => {
      console.log(
        "[Yjs DOC] Update fired! origin:",
        origin,
        "size:",
        update.length,
      );
    };
    yDoc.on("update", yjsUpdateHandler);

    // Create the Monaco binding for Yjs
    const binding = new MonacoBinding(
      yText,
      model,
      new Set([editor]),
      provider.awareness,
    );

    console.log(
      "[MonacoEditor] MonacoBinding created, initial content:",
      model.getValue(),
    );

    bindingRef.current = binding;

    return () => {
      console.log("[MonacoEditor] Destroying MonacoBinding");
      yDoc.off("update", yjsUpdateHandler);
      binding.destroy();
      bindingRef.current = null;
    };
  }, [isReady, provider, roomId, yDoc, yText]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (bindingRef.current) {
        bindingRef.current.destroy();
        bindingRef.current = null;
      }
      if (editorRef.current) {
        editorRef.current.dispose();
        editorRef.current = null;
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: "100%", minHeight: "500px" }}
    />
  );
});

export default MonacoEditor;
