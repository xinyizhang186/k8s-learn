package trigger

import (
	"context"
)

type Trigger interface {
	Start(ctx context.Context)
}
