package features

const (
    ExampleGate featuregate.Feature = "ExampleGate"
    NewGate featuregate.Feature = "ConfiguredNewGate"
)

var defaultVersionedKubernetesFeatureGates = map[featuregate.Feature]featuregate.VersionedSpecs{
    ExampleGate: {
        {Version: version.MustParse("1.34"), Default: false, PreRelease: featuregate.Alpha},
        {Version: version.MustParse("1.35"), Default: false, PreRelease: featuregate.Beta},
        {Version: version.MustParse("1.36"), Default: true, PreRelease: featuregate.GA, LockToDefault: true},
    },
    NewGate: {
        {Version: version.MustParse("1.36"), Default: false, PreRelease: featuregate.Alpha},
    },
}

