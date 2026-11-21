package main

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
)

const termsDenial = "This service has been disabled in this account for violation of Terms of Service."

type message struct {
	Role    string          `json:"role"`
	Content json.RawMessage `json:"content"`
}

type toolResult struct {
	Type      string          `json:"type"`
	ToolUseID string          `json:"tool_use_id"`
	Content   json.RawMessage `json:"content"`
}

func toolRounds(messages []message) int {
	rounds := 0
	for _, msg := range messages {
		var blocks []toolResult
		if msg.Role != "user" || json.Unmarshal(msg.Content, &blocks) != nil {
			continue
		}
		for _, block := range blocks {
			if block.Type == "tool_result" &&
				block.ToolUseID == fmt.Sprintf("tool_read_%d", rounds+1) &&
				strings.Contains(string(block.Content), fmt.Sprintf("fixture-file-%d", rounds+1)) {
				rounds++
			}
		}
	}
	return rounds
}

func event(w http.ResponseWriter, kind string, fields map[string]any) {
	fields["type"] = kind
	body, err := json.Marshal(fields)
	if err != nil {
		panic(err)
	}
	fmt.Fprintf(w, "event: %s\ndata: %s\n\n", kind, body)
}

func apiError(w http.ResponseWriter, status int, kind, reason string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(map[string]any{
		"type": "error", "error": map[string]string{"type": kind, "message": reason},
	})
}

func stream(w http.ResponseWriter, model string, rounds int, mode string) int {
	w.Header().Set("Content-Type", "text/event-stream")
	events := 0
	send := func(kind string, fields map[string]any) {
		event(w, kind, fields)
		events++
	}
	send("message_start", map[string]any{"message": map[string]any{
		"id": fmt.Sprintf("msg_%d", rounds), "type": "message", "role": "assistant",
		"model": model, "content": []any{}, "stop_reason": nil, "stop_sequence": nil,
		"usage": map[string]int{"input_tokens": 42, "output_tokens": 0},
	}})
	reason := "end_turn"
	block := map[string]any{"type": "text", "text": ""}
	delta := map[string]any{"type": "text_delta", "text": "Both fixture files were read."}
	switch {
	case mode == "truncated" || mode == "truncated-no-retries" || mode == "stream-error":
		delta["text"] = "Partial fixture response."
	case rounds < 2:
		reason = "tool_use"
		next := strconv.Itoa(rounds + 1)
		block = map[string]any{"type": "tool_use", "id": "tool_read_" + next, "name": "Read", "input": map[string]any{}}
		delta = map[string]any{"type": "input_json_delta", "partial_json": `{"file_path":"/tmp/probe` + next + `.txt"}`}
	}
	send("content_block_start", map[string]any{"index": 0, "content_block": block})
	send("content_block_delta", map[string]any{"index": 0, "delta": delta})
	switch mode {
	case "stream-error":
		send("error", map[string]any{"error": map[string]string{
			"type": "overloaded_error", "message": "Fixture stream error.",
		}})
		return events
	case "truncated", "truncated-no-retries":
		w.(http.Flusher).Flush()
		conn, _, err := w.(http.Hijacker).Hijack()
		if err != nil {
			panic(err)
		}
		conn.Close()
		return events
	}
	send("content_block_stop", map[string]any{"index": 0})
	send("message_delta", map[string]any{
		"delta": map[string]any{"stop_reason": reason, "stop_sequence": nil},
		"usage": map[string]int{"output_tokens": 16},
	})
	send("message_stop", map[string]any{})
	return events
}

func main() {
	mode, ready := os.Args[1], os.Args[2]
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		log.Fatal(err)
	}
	if err := os.WriteFile(ready, []byte("http://"+listener.Addr().String()), 0600); err != nil {
		log.Fatal(err)
	}

	var mutex sync.Mutex
	requests := 0
	var initialBody [sha256.Size]byte
	http.HandleFunc("/v1/messages", func(w http.ResponseWriter, r *http.Request) {
		var request struct {
			Model    string    `json:"model"`
			Stream   bool      `json:"stream"`
			Messages []message `json:"messages"`
		}
		body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 1024*1024))
		if r.Method != http.MethodPost || err != nil || json.Unmarshal(body, &request) != nil {
			http.Error(w, "invalid fixture request", http.StatusBadRequest)
			return
		}
		rounds := toolRounds(request.Messages)
		digest := sha256.Sum256(body)
		mutex.Lock()
		defer mutex.Unlock()
		requests++
		if requests == 1 {
			initialBody = digest
		}
		sameBody := digest == initialBody
		status, events := http.StatusOK, 0
		switch {
		case mode == "denial":
			status = http.StatusForbidden
			apiError(w, status, "permission_error", termsDenial)
		case mode == "recovery" && requests <= 2:
			status = http.StatusServiceUnavailable
			w.Header().Set("Retry-After", "1")
			apiError(w, status, "overloaded_error", "Temporary fixture overload.")
		case (mode == "truncated" || mode == "truncated-no-retries") && requests > 1:
			status = http.StatusForbidden
			apiError(w, status, "permission_error", "Fixture received another request after truncation.")
		case !request.Stream || rounds > 2:
			status = http.StatusBadRequest
			http.Error(w, "unexpected fixture request", status)
		default:
			events = stream(w, request.Model, rounds, mode)
		}
		fmt.Printf("rounds=%d stream=%t same_first_body=%t status=%d sse_events=%d\n",
			rounds, request.Stream, sameBody, status, events)
	})
	log.Fatal(http.Serve(listener, nil))
}
