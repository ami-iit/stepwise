import dataclasses

import casadi as cs
import numpy as np

from hippopt.robot_planning.utilities.terrain_descriptor import TerrainDescriptor
from hippopt.robot_planning.utilities.terrain_visualizer import (
    TerrainVisualizer,
    TerrainVisualizerSettings,
)


@dataclasses.dataclass
class SmoothTerrain(TerrainDescriptor):
    """
    Smooth terrain is a terrain with a smooth height function.
    The height is defined as follows:
    h(x, y) = exp(−g(x, y)^(2s)) π(x, y).

    Here, g(x, y) ≥ 0 is the equation of a closed curve in the xy-plane,
    and π(x, y) is the equation of a plane in the xy-plane, defining the shape of the
    terrain when exp(−g(x, y)^(2s)) = 1, i.e. when g(x, y) = 0.
    The parameter s ≥ 1 controls the smoothness of the terrain.

    Independently of the value of s, the value of exp(−g(.)^(2s)) is always passing
    through 1 when g(x,y) = 0, and through 1/e when g(x,y) = 1. Then, it will
    tend to zero as g(x, y) → ∞. The parameter s controls how fast exp(−g(.)^(2s)) tends
    to zero as g(x, y) grows. By multiplying times the equation of a plane, i.e.
    π(x, y), we can control the inclination of the top surface when g(x, y) = 0.
    Instead, g(x, y) = 1 controls the shape of the terrain at height 1/e * π(x, y).

    For example, to define a classical step with a square base of dimension l,
    we can use:
    g(x, y) = |2/l * x|^p + |2/l * y|^p
    π(x, y) = 1
    where p ≥ 1 is a parameter controlling the sharpness of the edges of the square
    at height 1/e.
    Here g(x, y) = 0 only at the origin, hence, the top surface is flat at the origin,
    and the parameter s determines the sharpness of the top face.

    It is then possible to specify a position offset and a transformation matrix to
    move, rotate, and scale the terrain.
    In particular, we have that:
    [x, y, z]^T = R^T * ([x_i, y_i, z_i]^T - [x_offset, y_offset, z_offset]^T)
    where [x_i, y_i, z_i]^T is the position of the point in the inertial frame, R is
    the transformation matrix, and [x_offset, y_offset, z_offset]^T is the offset.
    When applying a transformation matrix, it is also possible to rotate the terrain.
    Because of the choice of the projection method, the modified z axis needs to be
    parallel to the original one (i.e. no rotations around x or y are allowed).

    """

    _shape_function: cs.Function = dataclasses.field(default=None)
    _top_surface_function: cs.Function = dataclasses.field(default=None)
    _sharpness: float = dataclasses.field(default=None)
    _offset: np.ndarray = dataclasses.field(default=None)
    _transformation_matrix: np.ndarray = dataclasses.field(default=None)

    shape_function: dataclasses.InitVar[cs.Function] = dataclasses.field(default=None)
    top_surface_function: dataclasses.InitVar[cs.Function] = dataclasses.field(
        default=None
    )
    sharpness: dataclasses.InitVar[float] = dataclasses.field(default=None)
    offset: dataclasses.InitVar[np.ndarray] = dataclasses.field(default=None)
    transformation_matrix: dataclasses.InitVar[np.ndarray] = dataclasses.field(
        default=None
    )

    def __post_init__(
        self,
        point_position_name: str = None,
        options: dict = None,
        name: str = None,
        shape_function: cs.Function = None,
        top_surface_function: cs.Function = None,
        sharpness: float = None,
        offset: np.ndarray = None,
        transformation_matrix: np.ndarray = None,
    ):
        TerrainDescriptor.__post_init__(self, point_position_name, options, name)

        if self._sharpness is None:
            self._sharpness = 10.0

        if self._offset is None:
            self._offset = np.zeros(3)

        if self._transformation_matrix is None:
            self._transformation_matrix = np.eye(3)

        point_position_xy = cs.MX.sym(self.get_point_position_name() + "_xy", 2)
        if self._shape_function is None:
            self._shape_function = cs.Function(
                "smooth_terrain_shape",
                [point_position_xy],
                [(2 * point_position_xy[0]) ** 10 + (2 * point_position_xy[1]) ** 10],
                [point_position_xy.name()],
                ["g"],
                self._options,
            )
        if self._top_surface_function is None:
            self._top_surface_function = cs.Function(
                "smooth_terrain_top_surface",
                [point_position_xy],
                [cs.MX(0.5)],
                [point_position_xy.name()],
                ["pi"],
                self._options,
            )

        self.set_terrain(
            shape_function=shape_function,
            top_surface_function=top_surface_function,
            sharpness=sharpness,
            offset=offset,
            transformation_matrix=transformation_matrix,
        )

    def set_terrain(
        self,
        shape_function: cs.Function = None,
        top_surface_function: cs.Function = None,
        sharpness: float = None,
        offset: np.ndarray = None,
        transformation_matrix: np.ndarray = None,
    ) -> None:
        if isinstance(shape_function, cs.Function):
            if shape_function.n_in() != 1:
                raise ValueError(
                    "The shape function must have exactly one input argument."
                )
            if shape_function.n_out() != 1:
                raise ValueError(
                    "The shape function must have exactly one output argument."
                )
            if shape_function.numel_in() != 2:
                raise ValueError(
                    "The input argument of the shape function must be a 2D vector."
                )
            self._shape_function = shape_function

        if isinstance(top_surface_function, cs.Function):
            if top_surface_function.n_in() != 1:
                raise ValueError(
                    "The top surface function must have exactly one input argument."
                )
            if top_surface_function.n_out() != 1:
                raise ValueError(
                    "The top surface function must have exactly one output argument."
                )
            if top_surface_function.numel_in() != 2:
                raise ValueError(
                    "The input argument of the top surface function"
                    " must be a 2D vector."
                )
            self._top_surface_function = top_surface_function

        if sharpness is not None:
            if sharpness < 1:
                raise ValueError(
                    "The sharpness parameter must be greater than or equal to 1."
                )
            self._sharpness = sharpness

        if offset is not None:
            if not isinstance(offset, np.ndarray):
                raise TypeError("The offset must be a numpy array.")
            if offset.size != 3:
                raise ValueError("The offset must be a 3D vector.")
            self._offset = offset

        if transformation_matrix is not None:
            if not isinstance(transformation_matrix, np.ndarray):
                raise TypeError("The transformation matrix must be a numpy matrix.")
            if transformation_matrix.shape != (3, 3):
                raise ValueError("The transformation matrix must be a 3x3 matrix.")
            if (
                np.abs(np.linalg.det(transformation_matrix)) < 1e-6
                or (np.linalg.norm(transformation_matrix, axis=0) < 1e-6).any()
            ):
                raise ValueError(
                    "The transformation matrix must be invertible and have a non-zero"
                    " norm for each column."
                )
            if np.abs(np.dot(transformation_matrix[:, 2], [0, 0, 1])) < (
                1 - 1e-6
            ) * np.linalg.norm(transformation_matrix[:, 2]):
                raise ValueError(
                    "The transformation matrix should not change"
                    " the z axis orientation."
                )
            self._transformation_matrix = transformation_matrix

        self.invalidate_functions()

    def create_height_function(self) -> cs.Function:
        point_position = cs.MX.sym(self.get_point_position_name(), 3)

        position_in_terrain_frame = np.linalg.inv(self._transformation_matrix) @ cs.MX(
            point_position - self._offset,
        )

        shape = self._shape_function(position_in_terrain_frame[:2])
        top_surface = self._top_surface_function(position_in_terrain_frame[:2])

        z_terrain = cs.exp(-(shape ** (2 * self._sharpness))) * top_surface
        terrain_position = (
            self._transformation_matrix
            @ cs.vertcat(position_in_terrain_frame[:2], z_terrain)
            + self._offset
        )

        height = point_position[2] - terrain_position[2]

        return cs.Function(
            "smooth_terrain_height",
            [point_position],
            [height],
            [self.get_point_position_name()],
            ["point_height"],
            self._options,
        )


if __name__ == "__main__":
    viz_settings = TerrainVisualizerSettings()
    rotation_x = np.array(
        [
            [np.cos(np.pi / 4), -np.sin(np.pi / 4), 0],
            [np.sin(np.pi / 4), np.cos(np.pi / 4), 0],
            [0, 0, 1],
        ]
    )
    viz_settings.terrain = SmoothTerrain(
        transformation_matrix=rotation_x, offset=np.array([0, 0, 0.2])
    )
    viz_settings.overwrite_terrain_files = True
    viz_settings.draw_terrain_frames = True
    viz = TerrainVisualizer(viz_settings)
    input("Press Enter to exit.")
