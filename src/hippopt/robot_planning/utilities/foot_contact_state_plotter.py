import copy
import dataclasses
import logging
import math
import multiprocessing
from typing import TypeVar

import matplotlib.axes
import matplotlib.pyplot as plt
import numpy as np

from hippopt.robot_planning.utilities.terrain_descriptor import (
    PlanarTerrain,
    TerrainDescriptor,
)
from hippopt.robot_planning.variables.contacts import (
    ContactPointState,
    FootContactState,
)


@dataclasses.dataclass
class ContactPointStatePlotterSettings:
    axes: list[matplotlib.axes.Axes] | None = dataclasses.field(default=None)
    terrain: TerrainDescriptor = dataclasses.field(default=None)

    input_axes: dataclasses.InitVar[list[matplotlib.axes.Axes]] = dataclasses.field(
        default=None
    )
    input_terrain: dataclasses.InitVar[TerrainDescriptor] = dataclasses.field(
        default=None
    )

    def __post_init__(
        self, input_axes: list[matplotlib.axes.Axes], input_terrain: TerrainDescriptor
    ):
        self.axes = None
        if isinstance(input_axes, list):
            if len(input_axes) != 2:
                raise ValueError("input_axes must be a list of length 2.")

            self.axes = input_axes

        self.terrain = (
            input_terrain
            if isinstance(input_terrain, TerrainDescriptor)
            else PlanarTerrain()
        )


class ContactPointStatePlotter:
    def __init__(
        self,
        settings: ContactPointStatePlotterSettings = ContactPointStatePlotterSettings(),
    ):
        self.settings = settings
        self._axes = self.settings.axes
        self._fig = None

    def plot_complementarity(
        self,
        states: list[ContactPointState],
        time_s: float | list[float] | np.ndarray = None,
        title: str = "Contact Point Complementarity",
    ):
        _time_s = copy.deepcopy(time_s)
        if _time_s is None or isinstance(_time_s, float) or _time_s.size == 1:
            single_step = _time_s if _time_s is not None else 0.0
            _time_s = np.linspace(0, len(states) * single_step, len(states))

        if len(_time_s) != len(states):
            raise ValueError(
                "timestep_s and foot_contact_states have different lengths."
            )

        if self._axes is None:
            self._fig, self._axes = plt.subplots(nrows=1, ncols=2)
            plt.tight_layout()

        height_function = self.settings.terrain.height_function()
        normal_direction_fun = self.settings.terrain.normal_direction_function()

        positions = np.array([height_function(s.p) for s in states]).flatten()
        forces = np.array([normal_direction_fun(s.p).T @ s.f for s in states]).flatten()
        complementarity_error = np.multiply(positions, forces)
        self._axes[1].plot(_time_s, complementarity_error)
        self._axes[1].set_ylabel("Complementarity Error [Nm]")
        self._axes[1].set_xlabel("Time [s]")
        self._axes[0].plot(_time_s, positions)
        self._axes[0].set_ylabel("Height [m]", color="C0")
        self._axes[0].tick_params(axis="y", color="C0", labelcolor="C0")
        axes_force = self._axes[0].twinx()
        axes_force.plot(_time_s, forces, "C1")
        axes_force.set_ylabel("Normal Force [N]", color="C1")
        axes_force.tick_params(axis="y", color="C1", labelcolor="C1")
        axes_force.spines["right"].set_color("C1")
        axes_force.spines["left"].set_color("C0")

        if self._fig is not None:
            self._fig.suptitle(title)
            plt.draw()
            plt.pause(0.001)
            plt.show()


@dataclasses.dataclass
class FootContactStatePlotterSettings:
    number_of_columns: int = dataclasses.field(default=-1)
    terrain: TerrainDescriptor = dataclasses.field(default=None)


TFootContactStatePlotter = TypeVar(
    "TFootContactStatePlotter", bound="FootContactStatePlotter"
)


class FootContactStatePlotter:
    def __init__(
        self,
        settings: FootContactStatePlotterSettings = FootContactStatePlotterSettings(),
    ):
        self._settings = settings
        self._ext_process = None
        self._logger = logging.getLogger("[hippopt::FootContactStatePlotter]")

    def plot_complementarity(
        self,
        states: list[FootContactState],
        time_s: float | list[float] | np.ndarray = None,
        title: str = "Foot Contact Complementarity",
        blocking: bool = False,
    ):
        if self._ext_process is not None:
            self._logger.warning(
                "A plot is already running. "
                "Make sure to close the previous plot first."
            )
            self._ext_process.join()
            self._ext_process = None
        _time_s = copy.deepcopy(time_s)
        _states = copy.deepcopy(states)
        _terrain = copy.deepcopy(self._settings.terrain)
        if _time_s is None or isinstance(_time_s, float) or _time_s.size == 1:
            single_step = _time_s if _time_s is not None else 0.0
            _time_s = np.linspace(0, len(states) * single_step, len(states))

        if len(_time_s) != len(_states):
            raise ValueError(
                "timestep_s and foot_contact_states have different lengths."
            )

        if len(_states) == 0:
            return

        self._ext_process = multiprocessing.Process(
            target=FootContactStatePlotter._create_complementarity_plot,
            args=(
                _states,
                _time_s,
                title,
                self._settings.number_of_columns,
                _terrain,
            ),
        )
        self._ext_process.start()

        if blocking:
            self._ext_process.join()

    @staticmethod
    def _create_complementarity_plot(
        states: list[FootContactState],
        time_s: np.ndarray,
        title: str,
        number_of_columns: int,
        terrain: TerrainDescriptor,
    ):
        number_of_points = len(states[0])
        number_of_plots = number_of_points + 1
        _number_of_columns = (
            math.floor(math.sqrt(number_of_plots))
            if number_of_columns < 1
            else number_of_columns
        )
        number_of_rows = math.ceil(number_of_plots / _number_of_columns)

        _fig, axes_list = plt.subplots(
            nrows=number_of_rows,
            ncols=_number_of_columns,
            squeeze=False,
        )
        plt.tight_layout()
        last_plot_column = number_of_points - _number_of_columns * (number_of_rows - 1)
        last_plot = axes_list[number_of_rows - 1][last_plot_column]
        _point_plotters = [
            ContactPointStatePlotter(
                ContactPointStatePlotterSettings(
                    input_axes=[el, last_plot],
                    terrain=terrain,
                )
            )
            for row in axes_list
            for el in row
        ]
        for i in range(last_plot_column + 1, _number_of_columns):
            axes_list[number_of_rows - 1][i].remove()

        for p in range(number_of_points):
            contact_states = [state[p] for state in states]
            _point_plotters[p].plot_complementarity(
                states=contact_states, time_s=time_s
            )

        _fig.suptitle(title)
        plt.draw()
        plt.pause(0.001)
        plt.show()

    def close(self):
        if self._ext_process is not None:
            self._ext_process.terminate()
            self._ext_process = None
        plt.close("all")