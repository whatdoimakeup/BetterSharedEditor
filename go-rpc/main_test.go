package main

import (
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// TestHandleRPC_MethodNotAllowed verifies that GET requests are rejected.
func TestHandleRPC_MethodNotAllowed(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/rpc", nil)
	rec := httptest.NewRecorder()
	handleRPC(rec, req)
	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("expected 405, got %d", rec.Code)
	}
}

// TestHandleRPC_InvalidJSON verifies that malformed JSON is rejected.
func TestHandleRPC_InvalidJSON(t *testing.T) {
	req := httptest.NewRequest(http.MethodPost, "/rpc", strings.NewReader("not-json"))
	rec := httptest.NewRecorder()
	handleRPC(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

// TestHandleRPC_UnknownMethod verifies that unknown RPC methods are rejected.
func TestHandleRPC_UnknownMethod(t *testing.T) {
	body := `{"method":"unknown","data":{}}`
	req := httptest.NewRequest(http.MethodPost, "/rpc", strings.NewReader(body))
	rec := httptest.NewRecorder()
	handleRPC(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

// TestHandleRPC_MissingRoomID verifies that a request without room_id is rejected.
func TestHandleRPC_MissingRoomID(t *testing.T) {
	data := base64.StdEncoding.EncodeToString([]byte("somedata"))
	body, _ := json.Marshal(map[string]any{
		"method": "yjs_update",
		"data":   map[string]any{"data": data},
	})
	req := httptest.NewRequest(http.MethodPost, "/rpc", strings.NewReader(string(body)))
	rec := httptest.NewRecorder()
	handleRPC(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

// TestHandleRPC_InvalidBase64 verifies that bad base64 data is rejected.
func TestHandleRPC_InvalidBase64(t *testing.T) {
	body, _ := json.Marshal(map[string]any{
		"method": "yjs_update",
		"data": map[string]any{
			"room_id":   1,
			"data":      "!!!not-valid-base64!!!",
			"sender_id": "test",
		},
	})
	req := httptest.NewRequest(http.MethodPost, "/rpc", strings.NewReader(string(body)))
	rec := httptest.NewRecorder()
	handleRPC(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

// TestToInt covers the various input types accepted for room_id.
func TestToInt(t *testing.T) {
	cases := []struct {
		input    any
		expected int
		wantErr  bool
	}{
		{float64(42), 42, false},
		{int(7), 7, false},
		{"99", 99, false},
		{"notanumber", 0, true},
		{nil, 0, true},
	}
	for _, tc := range cases {
		got, err := toInt(tc.input)
		if tc.wantErr && err == nil {
			t.Errorf("toInt(%v): expected error, got nil", tc.input)
		}
		if !tc.wantErr && err != nil {
			t.Errorf("toInt(%v): unexpected error: %v", tc.input, err)
		}
		if !tc.wantErr && got != tc.expected {
			t.Errorf("toInt(%v): expected %d, got %d", tc.input, tc.expected, got)
		}
	}
}
