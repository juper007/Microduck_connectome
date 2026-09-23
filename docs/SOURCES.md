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

## SO-101 / LeRobot

### Hugging Face LeRobot repository
https://github.com/huggingface/lerobot

LeRobot provides a common `Robot` interface for supported robots. The documented contract includes `connect`, `disconnect`, `get_observation`, and `send_action`, allowing policies/adapters to target a stable robot abstraction instead of writing directly to low-level motor transports.

### Official SO-101 guide
https://github.com/huggingface/lerobot/blob/main/docs/source/so101.mdx

Important implementation details:
- the SO-101 follower is supported by LeRobot;
- the follower uses six STS3215 servos;
- LeRobot provides setup, USB port discovery, calibration, and follower configuration workflows;
- the Feetech dependency is installed through LeRobot's optional Feetech support;
- the follower can be created and controlled through the LeRobot SO follower API without requiring a leader arm for autonomous programmatic control.

### LeRobot Robot API
https://github.com/huggingface/lerobot/blob/main/docs/source/api/robots.mdx

The Robot API is the authoritative P11 integration boundary. P11 must use the supported observation/action lifecycle rather than introduce direct connectome-to-servo writes.

### SO-ARM100 / SO-101 hardware project
https://github.com/TheRobotStudio/SO-ARM100

Used as the upstream hardware/BOM reference linked by the official LeRobot SO-101 documentation.


## Source policy

Project documents must prefer:
1. official MaleCNS/Janelia sources,
2. primary neuroscience papers,
3. official MicroDuck repositories/docs,
4. official Hugging Face LeRobot and SO-101 upstream documentation for P11 robot integration.

Third-party simulators or interpretations may be evaluated, but cannot silently become the source of biological ground truth.
