package trigger

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"pprof-export/log"
	"pprof-export/pprof/exporter"
	pprofnames "pprof-export/pprof/names"
)

const SIGUSR2 = 0xc

type signalTrigger struct {
	exporter exporter.Exporter
}

func NewSignalTrigger(exporter exporter.Exporter) Trigger {
	return &signalTrigger{exporter: exporter}
}

func (t *signalTrigger) Start(ctx context.Context) {
	ch := make(chan os.Signal, 1)
	sig := []os.Signal{syscall.Signal(SIGUSR2)}
	signal.Notify(ch, sig...)

	log.Infof("signal trigger started, listening for SIGUSR2")

	for {
		select {
		case <-ctx.Done():
			signal.Stop(ch)
			log.Infof("signal trigger stopped")
			return
		case s := <-ch:
			log.Infof("receive signal: %v, exporting pprof", s)
			t.exporter.Export(pprofnames.AllProfiles())
		}
	}
}
