# Simulatore Franka FR3 su ROS 2 per l'API cobot.
# Build context: la radice di Procedure_DSL (serve la cartella ./cobot).
FROM ros:humble-ros-base-jammy

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

SHELL ["/bin/bash", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3-pip \
    python3-numpy \
    python3-colcon-common-extensions \
    ros-humble-xacro \
    ros-humble-robot-state-publisher \
    && rm -rf /var/lib/apt/lists/*

# Modello e mesh del FR3 (stessa versione usata da franka_ros2 humble)
WORKDIR /ws
RUN git clone --branch 2.8.1 --depth 1 https://github.com/frankarobotics/franka_description.git src/franka_description \
    && source /opt/ros/humble/setup.bash \
    && colcon build --packages-select franka_description

# Visualizzatore 3D locale: librerie JS scaricate in fase di build, nessuna CDN a runtime
RUN set -e; V=/opt/sim/viewer/vendor; B=https://cdn.jsdelivr.net/npm; \
    mkdir -p $V/jsm/loaders $V/jsm/controls $V/urdf; \
    curl -fsSL $B/three@0.160.0/build/three.module.js -o $V/three.module.js; \
    for f in ColladaLoader STLLoader TGALoader; do curl -fsSL $B/three@0.160.0/examples/jsm/loaders/$f.js -o $V/jsm/loaders/$f.js; done; \
    curl -fsSL $B/three@0.160.0/examples/jsm/controls/OrbitControls.js -o $V/jsm/controls/OrbitControls.js; \
    for f in URDFLoader URDFClasses; do curl -fsSL $B/urdf-loader@0.12.3/src/$f.js -o $V/urdf/$f.js; done

COPY cobot/requirements.txt /tmp/requirements.txt
RUN python3 -m pip install -r /tmp/requirements.txt

COPY cobot/app /srv/app
COPY cobot/src /srv/src
COPY cobot_sim/shim /opt/sim/shim
COPY cobot_sim/viewer/index.html /opt/sim/viewer/index.html
COPY cobot_sim/fake_desk.py cobot_sim/ros_bridge.py cobot_sim/entrypoint.sh /opt/sim/
RUN chmod +x /opt/sim/entrypoint.sh

WORKDIR /srv
EXPOSE 5001 8090
ENTRYPOINT ["/opt/sim/entrypoint.sh"]
