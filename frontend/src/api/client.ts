/**
 * API client for Django backend.
 */

import axios from "axios";

const API_BASE = "/api";

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    "Content-Type": "application/json",
  },
});

// --- Types ---

export interface RoomInfo {
  id: number;
  name: string;
  created_at: string;
  updated_at: string;
  has_content: boolean;
  has_state: boolean;
}

export interface RoomState {
  id: number;
  name: string;
  content: string;
  yjs_state: string | null; // base64 encoded
}

// --- Room API ---

export async function listRooms(): Promise<RoomInfo[]> {
  const response = await api.get<{ rooms: RoomInfo[] }>("/rooms/");
  return response.data.rooms;
}

export async function createRoom(name: string): Promise<RoomInfo> {
  const response = await api.post<RoomInfo>("/rooms/", { name });
  return response.data;
}

export async function getRoom(roomId: number): Promise<RoomInfo> {
  const response = await api.get<RoomInfo>(`/rooms/${roomId}/`);
  return response.data;
}

export async function deleteRoom(roomId: number): Promise<void> {
  await api.delete(`/rooms/${roomId}/`);
}

export async function getRoomState(roomId: number): Promise<RoomState> {
  const response = await api.get<RoomState>(`/rooms/${roomId}/state/`);
  return response.data;
}

export async function yjsUpdate(
  roomId: number,
  update: string,
  sender_id: string,
): Promise<void> {
  await api.post(`/rooms/${roomId}/yjs_update/`, { update, sender_id });
}

export async function saveRoomState(
  roomId: number,
  content: string,
  yjsState: string | null,
): Promise<{ status: string; updated_at: string }> {
  const response = await api.post(`/rooms/${roomId}/state/`, {
    content,
    yjs_state: yjsState,
  });
  return response.data;
}

export async function getCentrifugoToken(userId: string): Promise<string> {
  // For simplicity, we generate a simple anonymous token
  // In production, this would call a Django endpoint that returns a JWT
  // For now, we'll use the connection directly without a token
  return "";
}

export default api;
