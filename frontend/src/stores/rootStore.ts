/**
 * Root store combining all MobX stores.
 *
 * Provides singleton instances for use across the application.
 */

import { RoomStore } from "./RoomStore";
import { EditorStore } from "./EditorStore";

export const roomStore = new RoomStore();
export const editorStore = new EditorStore();
