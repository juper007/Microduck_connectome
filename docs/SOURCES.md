# Primary Sources

Accessed for planning on 2026-09-15.

## MaleCNS

### Official MaleCNS project
https://male-cns.janelia.org/

Key planning facts:
- MaleCNS v1.0 release announced 2026-06-08.
- MaleCNS paper publication announced 2026-09-03.
- project provides Cell Type Explorer, neuPrint, Clio, Neuroglancer and downloads.

### Official MaleCNS download / API page
https://male-cns.janelia.org/download/

Important implementation details:
- Python API: `neuprint-python`
- neuPrint dataset: `male-cns:v1.0`
- bulk graph file: `connectome-weights-male-cns-v1.0-minconf-0.5.feather`
- annotation and neurotransmitter files are separately available.
- MaleCNS connectome data is CC-BY according to the official download page.

### Google Research overview
https://research.google/blog/a-connectomics-milestone-mapping-the-complete-male-fruit-fly-brain/

The overview reports more than 166,000 neurons and roughly 125 million synaptic connections and highlights that the dataset includes the ventral nerve cord as well as the brain.

## MicroDuck

### Official runtime
https://github.com/pollen-robotics/microduck

The official repository describes:
- a 50 Hz control loop,
- fifteen servos,
- neural motion policies,
- `robotd` as the motor-control owner,
- JSON-RPC communication over Unix sockets.

### Official architecture
https://github.com/pollen-robotics/microduck/blob/main/docs/design/architecture.md

The architecture states that `robotd` is the only component that touches the robot/motor bus; clients send high-level intents and the safety layer decides what is executable.

### Official simulation
https://github.com/pollen-robotics/microduck/blob/main/docs/robot/simulation.md

The simulator runs the real daemons against a MuJoCo body. The same 50 Hz loop, policies, safety, fall detection, kinematics, odometry, and IPC surface are retained above the simulated I/O seam.

### RL / MuJoCo project
https://github.com/pollen-robotics/microduck_rl

Used for MicroDuck physics, policy training, and simulator body integration.

## Source policy

Project documents must prefer:
1. official MaleCNS/Janelia sources,
2. primary neuroscience papers,
3. official MicroDuck repositories/docs.

Third-party simulators or interpretations may be evaluated, but cannot silently become the source of biological ground truth.
