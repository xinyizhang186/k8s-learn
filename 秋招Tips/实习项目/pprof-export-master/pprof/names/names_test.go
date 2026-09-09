package names

import "testing"

func TestName_FileExt(t *testing.T) {
	tests := []struct {
		name 	 Name
		expected string
	}{
		{CPU, "cpu.profile"},
		{Heap, "heap.profile"},
		{Block, "block.profile"},
		{Mutex, "mutex.profile"},
		{Goroutine, "goroutine.profile"},
		{Name(100), ""},
	}

	for _, tt := range tests {
		t.Run(tt.expected, func(t *testing.T) {
			if got := tt.name.FileExt(); got != tt.expected {
				t.Errorf("Name.FileExt() = %v, want %v", got, tt.expected)
			}
		})
	}
}

func TestName_ProfileName(t *testing.T) {
	tests := []struct {
		name 	 Name
		expected string
	}{
		{CPU, "cpu"},
		{Heap, "heap"},
		{Block, "block"},
		{Mutex, "mutex"},
		{Goroutine, "goroutine"},
		{Name(100), ""},
	}

	for _, tt := range tests {
		t.Run(tt.expected, func(t *testing.T) {
			if got := tt.name.ProfileName(); got != tt.expected {
				t.Errorf("Name.ProfileName() = %v, want %v", got, tt.expected)
			}
		})
	}
}

func TestAllProfiles(t *testing.T) {
	got := AllProfiles()
	expected := Scope{CPU, Heap, Block, Mutex, Goroutine}

	if len(got) != len(expected) {
		t.Errorf("AllProfiles() length = %v, want %v", len(got), len(expected))
		return
	}

	for i := range got {
		if got[i] != expected[i] {
			t.Errorf("AllProfiles()[%d] = %v, want %v", i, got[i], expected[i])
		}
	}
}
