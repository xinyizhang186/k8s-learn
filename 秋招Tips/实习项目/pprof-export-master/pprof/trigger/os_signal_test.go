package trigger

import (
	"context"
	"testing"
	"time"

	"pprof-export/log"
	pprofnames "pprof-export/pprof/names"
)

func TestMain(m *testing.M) {
	log.Discard()
	m.Run()
}

type mockExporter struct {
	exportCalled int
}

func (m *mockExporter) Init() error {
	return nil
}

func (m *mockExporter) Export(scope pprofnames.Scope) {
	m.exportCalled++
}

func TestNewSignalTrigger(t *testing.T) {
	exp := &mockExporter{}
	trigger := NewSignalTrigger(exp)

	if trigger == nil {
		t.Fatal("NewSignalTrigger returned nil")
	}

	_, ok := trigger.(*signalTrigger)
	if !ok {
		t.Error("trigger is not a *signalTrigger")
	}
}

func TestSignalTriggerStartStop(t *testing.T) {
	exp := &mockExporter{}
	trigger := NewSignalTrigger(exp)

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
