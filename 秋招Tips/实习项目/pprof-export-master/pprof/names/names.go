package names

type Name int

const (
	CPU Name = iota
	Heap
	Block
	Mutex
	Goroutine
)

type Scope []Name

func (n Name) FileExt() string {
	switch n {
	case CPU:
		return "cpu.profile"
	case Heap:
		return "heap.profile"
	case Block:
		return "block.profile"
	case Mutex:
		return "mutex.profile"
	case Goroutine:
		return "goroutine.profile"
	default:
		return ""
	}
}

func (n Name) ProfileName() string {
	switch n {
	case CPU:
		return "cpu"
	case Heap:
		return "heap"
	case Block:
		return "block"
	case Mutex:
		return "mutex"
	case Goroutine:
		return "goroutine"
	default:
		return ""
	}
}

func AllProfiles() Scope {
	return Scope{CPU, Heap, Block, Mutex, Goroutine}
}
