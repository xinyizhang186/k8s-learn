// go:build !linux
//  +build !linux

package cgroups

var GetMemoryCgroupPaths = func() (memInUsePath, memLimitPath, memStatPath string) {
	return "", "", ""
}
