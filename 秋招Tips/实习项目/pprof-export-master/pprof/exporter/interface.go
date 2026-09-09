package exporter

import pprofnames "pprof-export/pprof/names"

type Exporter interface {
	Init() error
	Export(scope pprofnames.Scope)
}
