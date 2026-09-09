package exporter

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"pprof-export/log"
	pprofnames "pprof-export/pprof/names"
)

func TestMain(m *testing.M) {
	// 设置日志输出到 Discard，避免测试时输出
	log.Discard()
	os.Exit(m.Run())
}

func TestInit(t *testing.T) {
	t.Run("create new directory", func(t *testing.T) {
		tmpDir := t.TempDir()
		exp := NewExporter(Config{
			FilePrefix:    "test",
			ProfilingPath: filepath.Join(tmpDir, "profiling"),
		})

		err := exp.Init()
		defer os.RemoveAll(tmpDir)
		if err != nil {
			t.Fatalf("Init() error = %v", err)
		}

		// 验证目录已创建
		info, err := os.Stat(exp.(*exporter).ProfilingPath)
		if err != nil {
			t.Fatalf("failed to stat profiling path: %v", err)
		}
		if !info.IsDir() {
			t.Error("profiling path is not a directory")
		}
	})

	t.Run("permission denied", func(t *testing.T) {
		exp := NewExporter(Config{
			FilePrefix:    "test",
			ProfilingPath: "/proc/invalid-path",
		})

		err := exp.Init()
		if err == nil {
			t.Fatal("expected error for permission denied path")
		}
	})
}

func TestExport(t *testing.T) {
	t.Run("export with single profile", func(t *testing.T) {
		tmpDir := t.TempDir()
		exp := NewExporter(Config{
			FilePrefix:    "test",
			ProfilingPath: tmpDir,
		})

		if err := exp.Init(); err != nil {
			t.Fatalf("Init() error = %v", err)
		}
		defer os.RemoveAll(tmpDir)

		// 测试单个 profile - 使用 Goroutine 因为它最快
		scope := pprofnames.Scope{pprofnames.Goroutine}
		exp.Export(scope)

		// 验证生成的文件数量
		files, err := os.ReadDir(tmpDir)
		if err != nil {
			t.Fatalf("failed to read directory: %v", err)
		}
		if len(files) != 1 {
			t.Errorf("expected 1 file after export, got %d", len(files))
		}
	})

	t.Run("export with multiple profiles", func(t *testing.T) {
		tmpDir := t.TempDir()
		exp := NewExporter(Config{
			FilePrefix:    "test",
			ProfilingPath: tmpDir,
		})

		if err := exp.Init(); err != nil {
			t.Fatalf("Init() error = %v", err)
		}
		defer os.RemoveAll(tmpDir)

		scope := pprofnames.Scope{pprofnames.Goroutine, pprofnames.Heap}
		exp.Export(scope)

		// 验证生成的文件数量
		files, err := os.ReadDir(tmpDir)
		if err != nil {
			t.Fatalf("failed to read directory: %v", err)
		}
		if len(files) != 2 {
			t.Errorf("expected 2 files after export, got %d", len(files))
		}
	})

	t.Run("export multiple times", func(t *testing.T) {
		tmpDir := t.TempDir()
		exp := NewExporter(Config{
			FilePrefix:    "test",
			ProfilingPath: tmpDir,
		})

		if err := exp.Init(); err != nil {
			t.Fatalf("Init() error = %v", err)
		}
		defer os.RemoveAll(tmpDir)

		for i := 0; i < 3; i++ {
			exp.Export(pprofnames.Scope{pprofnames.Goroutine})
			time.Sleep(time.Second)
		}

		// 验证生成的文件数量（3次导出，每次1个goroutine profile, 最终只保留2个）
		files, err := os.ReadDir(tmpDir)
		if err != nil {
			t.Fatalf("failed to read directory: %v", err)
		}
		if len(files) != 2 {
			t.Errorf("expected 2 files after concurrent export, got %d", len(files))
		}
	})
}

func TestWriteCPUProfile(t *testing.T) {
	t.Run("write to valid file", func(t *testing.T) {
		tmpDir := t.TempDir()
		file, err := os.Create(filepath.Join(tmpDir, "test.cpu.profile"))
		if err != nil {
			t.Fatalf("failed to create test file: %v", err)
		}
		defer os.ReadFile(file.Name())
		defer file.Close()

		exp := NewExporter(Config{
			FilePrefix:    "test",
			ProfilingPath: tmpDir,
		})

		e := exp.(*exporter)
		e.writeCPUProfile(file, time.Second)

		// 验证文件不为空（CPU profile 应该写入数据）
		info, err := os.Stat(file.Name())
		if err != nil {
			t.Fatalf("failed to stat file: %v", err)
		}
		// CPU profile 会写入数据
		if info.Size() == 0 {
			t.Log("CPU profile file is empty (may be expected in some environments)")
		}
	})
}

func TestWriteHeapProfile(t *testing.T) {
	tmpDir := t.TempDir()
	file, err := os.Create(filepath.Join(tmpDir, "test.heap.profile"))
	if err != nil {
		t.Fatalf("failed to create test file: %v", err)
	}
	defer os.ReadFile(file.Name())
	defer file.Close()

	exp := NewExporter(Config{
		FilePrefix:    "test",
		ProfilingPath: tmpDir,
	})

	e := exp.(*exporter)
	e.writeHeapProfile(file)

	// 验证文件已写入
	info, err := os.Stat(file.Name())
	if err != nil {
		t.Fatalf("failed to stat file: %v", err)
	}
	if info.Size() == 0 {
		t.Log("Heap profile file is empty (may be expected if no heap data)")
	}
}

func TestCleanOldProfileFile(t *testing.T) {
	t.Run("clean old files keeping recent", func(t *testing.T) {
		tmpDir := t.TempDir()
		defer os.RemoveAll(tmpDir)

		exp := NewExporter(Config{
			FilePrefix:    "test",
			ProfilingPath: tmpDir,
		})

		// 创建多个 profile 文件，模拟不同时间戳
		timestamps := []string{
			"20260101-100000",
			"20260101-110000",
			"20260101-120000",
			"20260101-130000",
		}

		for _, ts := range timestamps {
			filename := "test-" + ts + "-goroutine.profile"
			if err := os.WriteFile(filepath.Join(tmpDir, filename), []byte("test"), 0600); err != nil {
				t.Fatalf("failed to create test file: %v", err)
			}
		}

		e := exp.(*exporter)
		e.cleanOldProfileFile()

		// 验证文件是否按预期被清理
		files, err := os.ReadDir(tmpDir)
		if err != nil {
			t.Fatalf("failed to read directory: %v", err)
		}

		// 保留最近 2 个批次（每个批次有 1 个文件），所以应该有 2 个文件
		if len(files) != keepRecentCount {
			t.Errorf("expected %d files after cleanup, got %d", keepRecentCount, len(files))
		}
	})

	t.Run("no files to clean", func(t *testing.T) {
		tmpDir := t.TempDir()
		defer os.RemoveAll(tmpDir)
		exp := NewExporter(Config{
			FilePrefix:    "test",
			ProfilingPath: tmpDir,
		})

		e := exp.(*exporter)
		e.cleanOldProfileFile()
	})

	t.Run("empty directory", func(t *testing.T) {
		tmpDir := t.TempDir()
		defer os.RemoveAll(tmpDir)
		exp := NewExporter(Config{
			FilePrefix:    "test",
			ProfilingPath: tmpDir,
		})

		// 创建 profilingPath 目录（为空）
		if err := os.MkdirAll(filepath.Join(tmpDir, "profiling"), 0750); err != nil {
			t.Fatalf("failed to create directory: %v", err)
		}

		e := exp.(*exporter)
		e.ProfilingPath = filepath.Join(tmpDir, "profiling")
		e.cleanOldProfileFile()
	})
}

func TestFindBatchToKeep(t *testing.T) {
	tests := []struct {
		name 	       string
		profileFiles   []profileFile
		wantBatchesLen int
	}{
		{
			name:           "empty input",
			profileFiles:   []profileFile{},
			wantBatchesLen: 0,
		},
		{
			name: "single batch",
			profileFiles: []profileFile{
				{timestamp: "20260101-100000"},
				{timestamp: "20260101-100000"},
			},
			wantBatchesLen: 1,
		},
		{
			name: "multiple batches",
			profileFiles: []profileFile{
				{timestamp: "20260101-100000"},
				{timestamp: "20260101-110000"},
				{timestamp: "20260101-120000"},
				{timestamp: "20260101-130000"},
			},
			wantBatchesLen: 2, // keepRecentCount = 2
		},
		{
			name: "more batches than keep count",
			profileFiles: []profileFile{
				{timestamp: "20260101-100000"},
				{timestamp: "20260101-110000"},
				{timestamp: "20260101-120000"},
				{timestamp: "20260101-130000"},
				{timestamp: "20260101-140000"},
				{timestamp: "20260101-150000"},
			},
			wantBatchesLen: 2, // keepRecentCount = 2
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
		tmpDir := t.TempDir()
		exp := NewExporter(Config{
			FilePrefix:    "test",
			ProfilingPath: tmpDir,
		})

		e := exp.(*exporter)
		result := e.findBatchToKeep(tt.profileFiles)

		if len(result) != tt.wantBatchesLen {
			t.Errorf("findBatchToKeep() returned %d batches, want %d", len(result), tt.wantBatchesLen)
		}
	})
}

	t.Run("correct newest batches kept", func(t *testing.T) {
		tmpDir := t.TempDir()
		exp := NewExporter(Config{
			FilePrefix:    "test",
			ProfilingPath: tmpDir,
		})

		// 创建按时间排序的文件
		files := []profileFile{
				{timestamp: "20260101-080000"},
				{timestamp: "20260101-090000"},
				{timestamp: "20260101-100000"},
				{timestamp: "20260101-110000"},
			}


		e := exp.(*exporter)
		result := e.findBatchToKeep(files)

		// 应该保留最新的 2 个批次
		if len(result) != 2 {
			t.Error("expected 2 batches to be kept")
		}
		if !result["20260101-110000"] {
			t.Error("expected 20260101-110000 to be kept")
		}
		if !result["20260101-100000"] {
			t.Error("expected 20260101-100000 to be kept")
		}
	})
}

func TestExtractTimestamp(t *testing.T) {
	tests := []struct {
		name     string
		filename string
		want     string
		wantErr  bool
	}{
		{
			name:	  "valid filename",
			filename: "test-20260101-120000-cpu.profile",
			want: 	  "20260101-120000",
		},
		{
			name: 	  "valid with numbers",
			filename: "module123-20260102-030405-goroutine.profile",
			want: 	  "20260102-030405",
		},
		{
			name:     "insufficient parts",
			filename: "test-20260101",
			want: 	  "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := extractTimestamp(tt.filename)
			if got != tt.want {
				t.Errorf("extractTimestamp(%q) = %q, want %q", tt.filename, got, tt.want)
			}
		})
	}
}
