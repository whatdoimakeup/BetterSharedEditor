/**
 * Save status indicator component.
 */

import { observer } from "mobx-react-lite";
import { editorStore } from "@/stores/rootStore";

const SaveStatus = observer(() => {
  const isSaving = editorStore.isSaving;
  const lastSaved = editorStore.lastSavedAt;
  const msgSizeKb = editorStore.lastMsgSizeKb;

  const sizeLabel =
    msgSizeKb !== null
      ? msgSizeKb < 1
        ? `${(msgSizeKb * 1024).toFixed(0)} B`
        : `${msgSizeKb.toFixed(2)} KB`
      : null;

  return (
    <div className="save-status-group">
      {isSaving && <span className="save-status saving">Saving...</span>}
      {!isSaving && lastSaved && (
        <span className="save-status saved">
          Saved at {new Date(lastSaved).toLocaleTimeString()}
        </span>
      )}
      {sizeLabel && (
        <span className="save-status msg-size">msg: {sizeLabel}</span>
      )}
    </div>
  );
});

export default SaveStatus;
