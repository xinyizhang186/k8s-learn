package trigger

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	pprofnames "pprof-export/pprof/names"
	"pprof-export/util/cgroups"
)

type mockMemoryPressureExporter struct {
	exportCalled int
}

func (m *mockMemoryPressureExporter) Init() error {
	return nil
}

func (m *mockMemoryPressureExporter) Export(scope pprofnames.Scope) {
	m.exportCalled++
}

func TestMemoryPressureTriggerStartStop(t *testing.T) {
	exp := &mockMemoryPressureExporter{}
	config := MemoryPressureConfig{
		CheckInterval:   10 * time.Millisecond,
		AlertMem:        0,
		AlertPercent:    0.99,
		MemoryIncrement: 0.1,
	}
	trigger := NewMemoryPressureTrigger(exp, config)

	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	done := make(chan struct{})
	go func() {
		trigger.Start(ctx)
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("Start did not exit after context cancellation")
	}
}

func TestExportOnAlert(t *testing.T) {
	tests := []struct {
		name                string
		memInUseContent     string
		memLimitContent     string
		memStatContent      string
		config              MemoryPressureConfig
		state               triggerState
		expectExport        int
		expectLastExportMem int64
	}{
		{
			name:            "first alert - should export",
			memInUseContent: "800000000\n",
			memLimitContent: "1000000000\n",
			memStatContent:  "active_file 100000000\ninactive_file 200000000\n",
			config: MemoryPressureConfig{
				AlertMem:        0,
				AlertPercent:    0.5,
				MemoryIncrement: 0.1,
			},
			state:               triggerState{},
			expectExport:        1,
			expectLastExportMem: 600000000,
		},
		{
			name:            "second alert with significant increase - should export",
			memInUseContent: "900000000\n",
			memLimitContent: "1000000000\n",
			memStatContent:  "active_file 100000000\ninactive_file 200000000\n",
			config: MemoryPressureConfig{
				AlertMem:        0,
				AlertPercent:    0.5,
				MemoryIncrement: 0.1,
			},
			state: triggerState{
				lastAlertTime:    time.Now().Add(-time.Minute),
				lastExportMemory: 600000000,
			},
			expectExport:        1,
			expectLastExportMem: 700000000,
		},
		{
			name:            "second alert with small increase - should not export",
			memInUseContent: "850000000\n",
			memLimitContent: "1000000000\n",
			memStatContent:  "active_file 100000000\ninactive_file 200000000\n",
			config: MemoryPressureConfig{
				AlertMem:        0,
				AlertPercent:    0.5,
				MemoryIncrement: 0.1,
			},
			state: triggerState{
				lastAlertTime:    time.Now().Add(-time.Minute),
				lastExportMemory: 600000000,
			},
			expectExport:        0,
			expectLastExportMem: 600000000,
		},
		{
			name:            "not on alert - memory below threshold",
			memInUseContent: "600000000\n",
			memLimitContent: "1000000000\n",
			memStatContent:  "active_file 100000000\ninactive_file 200000000\n",
			config: MemoryPressureConfig{
				AlertMem:        0,
				AlertPercent:    0.5,
				MemoryIncrement: 0.1,
			},
			state: triggerState{
				lastAlertTime:    time.Now().Add(-time.Minute),
				lastExportMemory: 600000000,
			},
			expectExport:        0,
			expectLastExportMem: 600000000,
		},
		{
			name:            "not on alert - reset lastExportMemory after timeout",
			memInUseContent: "600000000\n",
			memLimitContent: "1000000000\n",
			memStatContent:  "active_file 100000000\ninactive_file 200000000\n",
			config: MemoryPressureConfig{
				AlertMem:        0,
				AlertPercent:    0.5,
				MemoryIncrement: 0.1,
			},
			state: triggerState{
				lastAlertTime:    time.Now().Add(-15 * time.Minute),
				lastExportMemory: 600000000,
			},
			expectExport:        0,
			expectLastExportMem: 0,
		},
		{
			name:            "alert by absolute memory - above threshold",
			memInUseContent: "950001000\n",
			memLimitContent: "1000000000\n",
			memStatContent:  "active_file 100000000\ninactive_file 1000\n",
			config: MemoryPressureConfig{
				AlertMem:        100 * 1024 * 1024,
				AlertPercent:    0,
				MemoryIncrement: 0.1,
			},
			state:               triggerState{},
			expectExport:        1,
			expectLastExportMem: 950000000,
		},
		{
			name:            "read memory error - should not export",
			memInUseContent: "invalid\n",
			memLimitContent: "1000000000\n",
			memStatContent:  "active_file 100000000\ninactive_file 200000000\n",
			config: MemoryPressureConfig{
				AlertMem:        0,
				AlertPercent:    0.5,
				MemoryIncrement: 0.1,
			},
			state:               triggerState{},
			expectExport:        0,
			expectLastExportMem: 0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tmpDir := t.TempDir()
			defer os.Remove(tmpDir)

			memInUsePath := filepath.Join(tmpDir, "memory.usage_in_bytes")
			memLimitPath := filepath.Join(tmpDir, "memory.limit_in_bytes")
			memStatPath := filepath.Join(tmpDir, "memory.stat")

			if err := os.WriteFile(memInUsePath, []byte(tt.memInUseContent), 0644); err != nil {
				t.Fatalf("failed to create memInUse file: %v", err)
			}
			if err := os.WriteFile(memLimitPath, []byte(tt.memLimitContent), 0644); err != nil {
				t.Fatalf("failed to create memLimit file: %v", err)
			}
			if err := os.WriteFile(memStatPath, []byte(tt.memStatContent), 0644); err != nil {
				t.Fatalf("failed to create memStat file: %v", err)
			}

			// Backup and replace getCgroupPaths
			origGetCgroupPaths := cgroups.GetMemoryCgroupPaths
			cgroups.GetMemoryCgroupPaths = func() (string, string, string) {
				return memInUsePath, memLimitPath, memStatPath
			}
			defer func() { cgroups.GetMemoryCgroupPaths = origGetCgroupPaths }()

			mockExp := &mockMemoryPressureExporter{}
			m := &memoryPressureTrigger{
				exporter: mockExp,
				MemoryPressureConfig: MemoryPressureConfig{
					AlertMem:        tt.config.AlertMem,
					AlertPercent:    tt.config.AlertPercent,
					MemoryIncrement: tt.config.MemoryIncrement,
				},
			}

			stateCopy := tt.state
			m.exportOnAlert(&stateCopy)

			if mockExp.exportCalled != tt.expectExport {
				t.Errorf("export called = %v, want %v", mockExp.exportCalled, tt.expectExport)
			}
			if stateCopy.lastExportMemory != tt.expectLastExportMem {
				t.Errorf("lastExportMemory = %v, want %v", stateCopy.lastExportMemory, tt.expectLastExportMem)
			}

		})
	}
}

func TestFixClockJump(t *testing.T) {
	tests := []struct {
		name          string
		lastAlertTime time.Time
		expected      time.Time
	}{
		{
			name:          "normal case - lastAlertTime in past",
			lastAlertTime: time.Now().Add(-time.Hour),
			expected:      time.Now().Add(-time.Hour),
		},
		{
			name:          "clock jump forward - lastAlertTime in future",
			lastAlertTime: time.Now().Add(time.Hour),
			expected:      time.Now(),
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := fixClockJump(tt.lastAlertTime)
			diff := result.Sub(tt.expected)
			if diff < 0 {
				diff = -diff
			}
			if diff > time.Second {
				t.Errorf("fixClockJump() returned %v, expected %v (diff %v)", result, tt.expected, diff)
			}
		})
	}
}

func TestShouldExport(t *testing.T) {
	tests := []struct {
		name             string
		memInUsage       int64
		memLimit         int64
		lastExportMemory int64
		memoryIncrement  float64
		expected         bool
	}{
		{
			name:             "first export - should export",
			memInUsage:       800 * 1024 * 1024,
			memLimit:         1024 * 1024 * 1024,
			lastExportMemory: 0,
			memoryIncrement:  0.1,
			expected:         true,
		},
		{
			name:             "no memory increase - should not export",
			memInUsage:       800 * 1024 * 1024,
			memLimit:         1024 * 1024 * 1024,
			lastExportMemory: 800 * 1024 * 1024,
			memoryIncrement:  0.1,
			expected:         false,
		},
		{
			name:             "small increase below threshold - should not export",
			memInUsage:       850 * 1024 * 1024,
			memLimit:         1024 * 1024 * 1024,
			lastExportMemory: 800 * 1024 * 1024,
			memoryIncrement:  0.1,
			expected:         false,
		},
		{
			name:             "increase above threshold - should export",
			memInUsage:       920 * 1024 * 1024,
			memLimit:         1024 * 1024 * 1024,
			lastExportMemory: 800 * 1024 * 1024,
			memoryIncrement:  0.1,
			expected:         true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			m := &memoryPressureTrigger{
				MemoryPressureConfig: MemoryPressureConfig{
					MemoryIncrement: tt.memoryIncrement,
				},
			}
			result := m.shouldExport(tt.memInUsage, tt.memLimit, tt.lastExportMemory)
			if result != tt.expected {
				t.Errorf("shouldExport() = %v, want %v", result, tt.expected)
			}
		})
	}
}

func TestIsOnAlert(t *testing.T) {
	tests := []struct {
		name         string
		alertMem     int64
		alertPercent float64
		memInUsage   int64
		memLimit     int64
		expected     bool
	}{
		{
			name:         "alert by absolute memory - below threshold",
			alertMem:     100 * 1024 * 1024,
			alertPercent: 0,
			memInUsage:   900 * 1024 * 1024,
			memLimit:     1024 * 1024 * 1024,
			expected:     false,
		},
		{
			name:         "alert by absolute memory - above threshold",
			alertMem:     100 * 1024 * 1024,
			alertPercent: 0,
			memInUsage:   950 * 1024 * 1024,
			memLimit:     1024 * 1024 * 1024,
			expected:     true,
		},
		{
			name:         "alert by percentage - below threshold",
			alertMem:     0,
			alertPercent: 0.9,
			memInUsage:   800 * 1024 * 1024,
			memLimit:     1024 * 1024 * 1024,
			expected:     false,
		},
		{
			name:         "alert by percentage - at threshold",
			alertMem:     0,
			alertPercent: 0.9,
			memInUsage:   921 * 1024 * 1024,
			memLimit:     1024 * 1024 * 1024,
			expected:     false,
		},
		{
			name:         "alert by percentage - above threshold",
			alertMem:     0,
			alertPercent: 0.9,
			memInUsage:   930 * 1024 * 1024,
			memLimit:     1024 * 1024 * 1024,
			expected:     true,
		},						
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			m := &memoryPressureTrigger{
				MemoryPressureConfig: MemoryPressureConfig{
					AlertMem:     tt.alertMem,
					AlertPercent: tt.alertPercent,
				},
			}
			result := m.isOnAlert(tt.memInUsage, tt.memLimit)
			if result != tt.expected {
				t.Errorf("isOnAlert() = %v, want %v", result, tt.expected)
			}
		})
	}
}

func TestReadFile(t *testing.T) {
	t.Run("valid uint64 content", func(t *testing.T) {
		tmpDir := t.TempDir()
		defer os.Remove(tmpDir)
		filePath := filepath.Join(tmpDir, "test.txt")
		err := os.WriteFile(filePath, []byte("1234567890\n"), 0644)
		if err != nil {
			t.Fatalf("failed to create test file: %v", err)
		}

		result, err := readFileValue(filePath)
		if err != nil {
			t.Fatalf("readFileValue() error = %v", err)
		}
		if result != 1234567890 {
			t.Errorf("readFileValue() = %v, want %v", result, 1234567890)
		}
	})

	t.Run("file not found", func(t *testing.T) {
		_, err := readFileValue("/nonexistent/path/file.txt")
		if err == nil {
			t.Error("expected error for nonexistent file")
		}
	})

	t.Run("invalid content", func(t *testing.T) {
		tmpDir := t.TempDir()
		defer os.Remove(tmpDir)
		filePath := filepath.Join(tmpDir, "test.txt")
		err := os.WriteFile(filePath, []byte("not a number\n"), 0644)
		if err != nil {
			t.Fatalf("failed to create test file: %v", err)
		}

		_, err = readFileValue(filePath)
		if err == nil {
			t.Error("expected error for invalid content")
		}
	})
}

func TestGetInactiveMem(t *testing.T) {
	tests := []struct {
		name        string
		content     string
		expected    uint64
		expectError bool
	}{
		{
			name:        "normal inactive_file entry",
			content:     "active_file 123456789\ninactive_file 987654321\nsome_other_entry 111",
			expected:    987654321,
			expectError: false,
		},
		{
			name:        "inactive_file at beginning",
			content:     "inactive_file 555555\nactive_file 666666",
			expected:    555555,
			expectError: false,
		},
		{
			name:        "inactive_file at end",
			content:     "some_entry 111\ninactive_file 777777",
			expected:    777777,
			expectError: false,
		},
		{
			name:        "inactive_file not found",
			content:     "total_active_file 123456789\nsome_other_entry 111",
			expected:    0,
			expectError: true,
		},
		{
			name:        "invalid inactive_file format",
			content:     "inactive_file only_one_field\nsome_other_entry 111",
			expected:    0,
			expectError: true,
		},
		{
			name:        "empty content",
			content:     "",
			expected:    0,
			expectError: true,
		},
		{
			name:        "file not found",
			content:     "",
			expected:    0,
			expectError: true,
		},											
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if tt.name == "file not found" {
				_, err := getInactiveMem("/nonexistent/path/memory.stat")
				if err == nil {
					t.Error("expected error for nonexistent file")
				}
				return
			}

			tmpDir := t.TempDir()
			filePath := filepath.Join(tmpDir, "memory.stat")
			err := os.WriteFile(filePath, []byte(tt.content), 0644)
			if err != nil {
				t.Fatalf("failed to create test file: %v", err)
			}

			result, err := getInactiveMem(filePath)
			if tt.expectError {
				if err == nil {
					t.Error("expected error but got nil")
				}
				return
			}
			if err != nil {
				t.Fatalf("getInactiveMem() error = %v", err)
			}
			if result != tt.expected {
				t.Errorf("getInactiveMem() = %v, want %v", result, tt.expected)
			}
		})
	}
}
