package features

const (
    ExampleGate featuregate.Feature = "ExampleGate"
    RemovedGate featuregate.Feature = "RemovedGate"
)

var defaultVersionedKubernetesFeatureGates = map[featuregate.Feature]featuregate.VersionedSpecs{
    ExampleGate: {
        {Version: version.MustParse("1.34"), Default: false, PreRelease: featuregate.Alpha},
        {Version: version.MustParse("1.35"), Default: false, PreRelease: featuregate.Beta},
    },
    RemovedGate: {
        {Version: version.MustParse("1.35"), Default: true, PreRelease: featuregate.GA, LockToDefault: true},
    },
}

