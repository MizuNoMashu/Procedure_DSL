FROM ros:humble-ros-base-jammy

ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=humble

SHELL ["/bin/bash", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    python3-pip \
    python3-rosdep \
    python3-vcstool \
    python3-colcon-common-extensions \
    ros-humble-moveit \
    ros-humble-ros2-control \
    ros-humble-ros2-controllers \
    && rm -rf /var/lib/apt/lists/*

RUN rosdep init 2>/dev/null || true && rosdep update

WORKDIR /franka_ros2_ws

# Il repository viene inserito direttamente nella cartella src,
# come indicato dalla procedura ufficiale Franka.
RUN git clone \
    --branch humble \
    --depth 1 \
    https://github.com/frankarobotics/franka_ros2.git \
    src

# Scarica le dipendenze dichiarate dal progetto Franka.
RUN vcs import src \
    < src/dependency.repos \
    --recursive \
    --skip-existing

RUN apt-get update && \
    rosdep install \
      --from-paths src \
      --ignore-src \
      --rosdistro humble \
      -y && \
    rm -rf /var/lib/apt/lists/*

RUN source /opt/ros/humble/setup.bash && \
    colcon build \
      --symlink-install \
      --cmake-args \
      -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_TESTS=OFF

WORKDIR /app

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY routes.py .
COPY moveit_client ./moveit_client
COPY entrypoint.sh .

RUN chmod +x /app/entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["/app/entrypoint.sh"]