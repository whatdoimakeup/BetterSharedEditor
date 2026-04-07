// go-rpc is a lightweight Go service that handles the Centrifugo RPC proxy.
//
// Instead of routing every Yjs update through Django (slow Python CRDT merge
// on the hot path), this service:
//   1. Decodes the incoming base64 Yjs update.
//   2. Appends the raw update bytes to a Redis pending list for the room.
//   3. Immediately broadcasts the original delta to all room subscribers via
//      the Centrifugo HTTP API.
//   4. Returns {"result": {}} to Centrifugo.
//
// Django continues to own the CRDT merge logic, but it now runs lazily —
// only when the full room state is actually needed (e.g. a new client joins
// or state is explicitly requested), not on every single keystroke.
package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/redis/go-redis/v9"
)

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

var (
	redisClient   *redis.Client
	centrifugoURL string
	centrifugoKey string
	httpClient    = &http.Client{Timeout: 5 * time.Second}
)

const (
	// Maximum number of pending updates kept per room in Redis.
	maxPendingUpdates = 10_000
	// TTL applied to the pending-updates list key (30 minutes).
	pendingUpdatesTTL = 30 * time.Minute
)

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func init() {
	redisURL := getEnv("REDIS_URL", "redis://localhost:6379/0")
	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		log.Fatalf("go-rpc: invalid REDIS_URL %q: %v", redisURL, err)
	}
	redisClient = redis.NewClient(opts)

	centrifugoURL = getEnv("CENTRIFUGO_API_URL", "http://centrifugo:8000")
	centrifugoKey = getEnv("CENTRIFUGO_API_KEY", "secret-api-key")
}

// ---------------------------------------------------------------------------
// Redis helpers
// ---------------------------------------------------------------------------

// pendingKey returns the Redis list key that stores raw pending Yjs updates.
func pendingKey(roomID int) string {
	return fmt.Sprintf("room:%d:pending_updates", roomID)
}

// appendPendingUpdate pushes one raw Yjs update onto the room's pending list.
// It trims the list to maxPendingUpdates and refreshes the TTL.
// Errors are logged but not fatal — broadcasting still proceeds.
func appendPendingUpdate(ctx context.Context, roomID int, update []byte) {
	key := pendingKey(roomID)
	pipe := redisClient.Pipeline()
	pipe.RPush(ctx, key, update)
	pipe.LTrim(ctx, key, -maxPendingUpdates, -1)
	pipe.Expire(ctx, key, pendingUpdatesTTL)
	if _, err := pipe.Exec(ctx); err != nil {
		log.Printf("go-rpc: Redis pipeline failed for room %d: %v", roomID, err)
	}
}

// ---------------------------------------------------------------------------
// Centrifugo HTTP API helper
// ---------------------------------------------------------------------------

// publishToRoom calls the Centrifugo HTTP API to publish a message to the
// room's channel so that all connected subscribers receive the update.
func publishToRoom(ctx context.Context, roomID int, data map[string]any) error {
	payload := map[string]any{
		"method": "publish",
		"params": map[string]any{
			"channel": fmt.Sprintf("rooms:%d", roomID),
			"data":    data,
		},
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, centrifugoURL+"/api", bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "apikey "+centrifugoKey)

	resp, err := httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("http do: %w", err)
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body) //nolint:errcheck

	if resp.StatusCode >= 400 {
		return fmt.Errorf("centrifugo returned HTTP %d", resp.StatusCode)
	}
	return nil
}

// ---------------------------------------------------------------------------
// RPC handler
// ---------------------------------------------------------------------------

// rpcRequest mirrors the JSON body that Centrifugo sends when proxying an
// RPC call from a client.
type rpcRequest struct {
	Method string         `json:"method"`
	Data   map[string]any `json:"data"`
	Client string         `json:"client"`
}

// handleRPC is the Centrifugo proxy_rpc_endpoint handler.
//
// It supports the single "yjs_update" method:
//
//	{method: "yjs_update", data: {room_id, data: <base64>, sender_id}}
//
// The handler:
//  1. Decodes the base64 Yjs update to raw bytes.
//  2. Appends those bytes to the room's Redis pending list.
//  3. Publishes the original delta (base64) to Centrifugo so all subscribers
//     can apply it immediately.
//  4. Returns {"result": {}} — the shape Centrifugo expects.
func handleRPC(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
		return
	}

	var req rpcRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid JSON"})
		return
	}

	if req.Method != "yjs_update" {
		writeJSON(w, http.StatusBadRequest, map[string]string{
			"error": fmt.Sprintf("unknown RPC method: %s", req.Method),
		})
		return
	}

	// --- Parse room_id ---
	roomIDRaw, ok := req.Data["room_id"]
	if !ok {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "missing room_id"})
		return
	}
	roomID, err := toInt(roomIDRaw)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid room_id"})
		return
	}

	// --- Parse base64 update ---
	dataB64, _ := req.Data["data"].(string)
	if dataB64 == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "missing data"})
		return
	}

	updateBytes, err := base64.StdEncoding.DecodeString(dataB64)
	if err != nil {
		// Centrifugo clients may encode with standard or URL-safe base64; try both.
		updateBytes, err = base64.URLEncoding.DecodeString(dataB64)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid base64 data"})
			return
		}
	}

	senderID, _ := req.Data["sender_id"].(string)

	ctx, cancel := context.WithTimeout(r.Context(), 4*time.Second)
	defer cancel()

	// 1. Store raw update bytes in Redis for lazy CRDT merging by Django.
	appendPendingUpdate(ctx, roomID, updateBytes)

	// 2. Broadcast the delta immediately to all room subscribers.
	if err := publishToRoom(ctx, roomID, map[string]any{
		"type":     "yjs-update",
		"senderId": senderID,
		"data":     dataB64,
	}); err != nil {
		log.Printf("go-rpc: failed to publish to room %d: %v", roomID, err)
		// Non-fatal: the update is already in Redis; clients will resync.
	}

	// Centrifugo expects {"result": <object>} on success.
	writeJSON(w, http.StatusOK, map[string]any{"result": map[string]any{}})
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		log.Printf("go-rpc: failed to write JSON response: %v", err)
	}
}

// toInt converts a JSON-decoded value (float64, string, or int) to int.
func toInt(v any) (int, error) {
	switch val := v.(type) {
	case float64:
		return int(val), nil
	case int:
		return val, nil
	case string:
		return strconv.Atoi(val)
	default:
		return 0, fmt.Errorf("cannot convert %T to int", v)
	}
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

func main() {
	port := getEnv("PORT", "8002")

	mux := http.NewServeMux()
	mux.HandleFunc("/rpc", handleRPC)
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})

	log.Printf("go-rpc: listening on :%s", port)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		log.Fatalf("go-rpc: server error: %v", err)
	}
}
