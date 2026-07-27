"""
Parsing minimale dell'SRDF pubblicato dal nodo move_group come parametro
'robot_description_semantic'.

Non dipende da alcuna libreria MoveIt: legge solo i tag che servono per
esporre via API i planning group, i target nominati (group_state) e il
link end-effector, senza dover conoscere in anticipo i nomi usati dal
pacchetto franka_fr3_moveit_config (che possono cambiare tra versioni).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class GroupInfo:
    name: str
    joint_names: list[str] = field(default_factory=list)
    base_link: str | None = None
    tip_link: str | None = None


@dataclass
class EndEffectorInfo:
    name: str
    parent_link: str
    parent_group: str
    group: str


@dataclass
class SrdfInfo:
    groups: dict[str, GroupInfo]
    # group_states[group_name][state_name] = {joint_name: value}
    group_states: dict[str, dict[str, dict[str, float]]]
    end_effectors: list[EndEffectorInfo]

    def default_group(self) -> str | None:
        """Sceglie il planning group dell'arm: quello referenziato da un
        end_effector come parent_group, oppure il gruppo con più giunti."""
        if self.end_effectors:
            return self.end_effectors[0].parent_group
        if not self.groups:
            return None
        return max(self.groups.values(), key=lambda g: len(g.joint_names)).name

    def default_eef_link(self, group_name: str | None = None) -> str | None:
        for ee in self.end_effectors:
            if group_name is None or ee.parent_group == group_name:
                return ee.parent_link
        if group_name and group_name in self.groups:
            return self.groups[group_name].tip_link
        return None


def parse_srdf(xml_text: str) -> SrdfInfo:
    root = ET.fromstring(xml_text)

    groups: dict[str, GroupInfo] = {}
    for group_el in root.findall("group"):
        name = group_el.get("name")
        if not name:
            continue
        info = GroupInfo(name=name)
        chain_el = group_el.find("chain")
        if chain_el is not None:
            info.base_link = chain_el.get("base_link")
            info.tip_link = chain_el.get("tip_link")
        for joint_el in group_el.findall("joint"):
            joint_name = joint_el.get("name")
            if joint_name:
                info.joint_names.append(joint_name)
        groups[name] = info

    group_states: dict[str, dict[str, dict[str, float]]] = {}
    for state_el in root.findall("group_state"):
        state_name = state_el.get("name")
        group_name = state_el.get("group")
        if not state_name or not group_name:
            continue
        joints = {}
        for joint_el in state_el.findall("joint"):
            joint_name = joint_el.get("name")
            value = joint_el.get("value")
            if joint_name is None or value is None:
                continue
            try:
                joints[joint_name] = float(value)
            except ValueError:
                continue
        group_states.setdefault(group_name, {})[state_name] = joints

    end_effectors: list[EndEffectorInfo] = []
    for ee_el in root.findall("end_effector"):
        name = ee_el.get("name")
        parent_link = ee_el.get("parent_link")
        parent_group = ee_el.get("parent_group")
        group = ee_el.get("group")
        if name and parent_link and group:
            end_effectors.append(
                EndEffectorInfo(
                    name=name,
                    parent_link=parent_link,
                    parent_group=parent_group or "",
                    group=group,
                )
            )

    return SrdfInfo(groups=groups, group_states=group_states, end_effectors=end_effectors)
