import copy
import dataclasses
from typing import Any, ClassVar, List

import casadi as cs
import numpy as np

from hippopt.base.optimization_object import OptimizationObject, TOptimizationObject
from hippopt.base.optimization_solver import (
    OptimizationSolver,
    ProblemNotRegisteredException,
    SolutionNotAvailableException,
)
from hippopt.base.parameter import Parameter
from hippopt.base.problem import Problem
from hippopt.base.variable import Variable


@dataclasses.dataclass
class OptiSolver(OptimizationSolver):
    DefaultSolverType: ClassVar[str] = "ipopt"
    _inner_solver: str = dataclasses.field(default=DefaultSolverType)
    problem_type: dataclasses.InitVar[str] = dataclasses.field(default="nlp")

    _options_plugin: dict[str, Any] = dataclasses.field(default_factory=dict)
    _options_solver: dict[str, Any] = dataclasses.field(default_factory=dict)
    options_solver: dataclasses.InitVar[dict[str, Any]] = dataclasses.field(
        default=None
    )
    options_plugin: dataclasses.InitVar[dict[str, Any]] = dataclasses.field(
        default=None
    )

    _cost: cs.MX = dataclasses.field(default=None)
    _solver: cs.Opti = dataclasses.field(default=None)
    _opti_solution: cs.OptiSol = dataclasses.field(default=None)
    _output_solution: TOptimizationObject | List[
        TOptimizationObject
    ] = dataclasses.field(default=None)
    _output_cost: float = dataclasses.field(default=None)
    _variables: TOptimizationObject | List[TOptimizationObject] = dataclasses.field(
        default=None
    )
    _problem: Problem = dataclasses.field(default=None)

    def __post_init__(
        self,
        problem_type: str,
        options_solver: dict[str, Any] = None,
        options_plugin: dict[str, Any] = None,
    ):
        self._solver = cs.Opti(problem_type)
        self._options_solver = (
            options_solver if isinstance(options_solver, dict) else {}
        )
        self._options_plugin = (
            options_plugin if isinstance(options_plugin, dict) else {}
        )
        self._solver.solver(
            self._inner_solver, self._options_plugin, self._options_solver
        )

    def _generate_opti_object(self, storage_type: str, name: str, value) -> cs.MX:
        if value is None:
            raise ValueError("Field " + name + " is tagged as storage, but it is None.")

        if isinstance(value, np.ndarray):
            if value.ndim > 2:
                raise ValueError(
                    "Field " + name + " has number of dimensions greater than 2."
                )
            if value.ndim < 2:
                value = np.expand_dims(value, axis=1)

        if storage_type is Variable.StorageTypeValue:
            return self._solver.variable(*value.shape)

        if storage_type is Parameter.StorageTypeValue:
            return self._solver.parameter(*value.shape)

        raise ValueError("Unsupported input storage type")

    def _generate_objects_from_instance(
        self, input_structure: TOptimizationObject
    ) -> TOptimizationObject:
        output = copy.deepcopy(input_structure)

        for field in dataclasses.fields(output):
            composite_value = output.__getattribute__(field.name)

            is_list = isinstance(composite_value, list)
            list_of_optimization_objects = is_list and all(
                isinstance(elem, OptimizationObject) or isinstance(elem, list)
                for elem in composite_value
            )

            if (
                isinstance(composite_value, OptimizationObject)
                or list_of_optimization_objects
            ):
                output.__setattr__(
                    field.name, self.generate_optimization_objects(composite_value)
                )
                continue

            if OptimizationObject.StorageTypeField in field.metadata:
                value_list = []
                value_field = dataclasses.asdict(output)[field.name]
                value_list.append(value_field)

                value_list = value_field if is_list else value_list
                output_value = []
                for value in value_list:
                    output_value.append(
                        self._generate_opti_object(
                            storage_type=field.metadata[
                                OptimizationObject.StorageTypeField
                            ],
                            name=field.name,
                            value=value,
                        )
                    )

                output.__setattr__(
                    field.name, output_value if is_list else output_value[0]
                )
                continue

        self._variables = output
        return output

    def _generate_objects_from_list(
        self, input_structure: List[TOptimizationObject]
    ) -> List[TOptimizationObject]:
        assert isinstance(input_structure, list)

        output = copy.deepcopy(input_structure)
        for i in range(len(output)):
            output[i] = self.generate_optimization_objects(output[i])

        self._variables = output
        return output

    # TODO Stefano: Handle the case where the storage is a list or a list of list
    def _generate_solution_output(
        self, variables: TOptimizationObject | List[TOptimizationObject]
    ) -> TOptimizationObject | List[TOptimizationObject]:
        output = copy.deepcopy(variables)

        if isinstance(variables, list):
            i = 0
            for element in variables:
                output[i] = self._generate_solution_output(element)
                i += 1

            return output

        for field in dataclasses.fields(variables):
            has_storage_field = OptimizationObject.StorageTypeField in field.metadata

            if has_storage_field and (
                (
                    field.metadata[OptimizationObject.StorageTypeField]
                    is Variable.StorageTypeValue
                )
                or (
                    field.metadata[OptimizationObject.StorageTypeField]
                    is Parameter.StorageTypeValue
                )
            ):
                var = dataclasses.asdict(variables)[field.name]
                output.__setattr__(field.name, np.array(self._opti_solution.value(var)))
                continue

            composite_variable = variables.__getattribute__(field.name)

            is_list = isinstance(composite_variable, list)
            list_of_optimization_objects = is_list and all(
                isinstance(elem, OptimizationObject) for elem in composite_variable
            )

            if (
                isinstance(composite_variable, OptimizationObject)
                or list_of_optimization_objects
            ):
                output.__setattr__(
                    field.name, self._generate_solution_output(composite_variable)
                )

        return output

    # TODO Stefano: Handle the case where the storage is a list or a list of list
    def _set_initial_guess_internal(
        self,
        initial_guess: TOptimizationObject,
        corresponding_variable: TOptimizationObject,
    ) -> None:
        for field in dataclasses.fields(initial_guess):
            has_storage_field = OptimizationObject.StorageTypeField in field.metadata

            if (
                has_storage_field
                and field.metadata[OptimizationObject.StorageTypeField]
                is Variable.StorageTypeValue
            ):
                guess = dataclasses.asdict(initial_guess)[field.name]

                if guess is None:
                    continue

                if not isinstance(guess, np.ndarray):
                    raise ValueError(
                        "The guess for the field "
                        + field.name
                        + " is not an numpy array."
                    )

                if not hasattr(corresponding_variable, field.name):
                    raise ValueError(
                        "The guess has the field "
                        + field.name
                        + " but it is not present in the optimization variables"
                    )

                corresponding_variable_value = corresponding_variable.__getattribute__(
                    field.name
                )

                input_shape = (
                    guess.shape if len(guess.shape) > 1 else (guess.shape[0], 1)
                )

                if corresponding_variable_value.shape != input_shape:
                    raise ValueError(
                        "The guess has the field "
                        + field.name
                        + " but its dimension does not match with the corresponding optimization variable"
                    )

                self._solver.set_initial(corresponding_variable_value, guess)
                continue

            if (
                has_storage_field
                and field.metadata[OptimizationObject.StorageTypeField]
                is Parameter.StorageTypeValue
            ):
                guess = dataclasses.asdict(initial_guess)[field.name]

                if guess is None:
                    continue

                if not isinstance(guess, np.ndarray):
                    raise ValueError(
                        "The guess for the field "
                        + field.name
                        + " is not an numpy array."
                    )

                if not hasattr(corresponding_variable, field.name):
                    raise ValueError(
                        "The guess has the field "
                        + field.name
                        + " but it is not present in the optimization parameters"
                    )

                corresponding_parameter_value = corresponding_variable.__getattribute__(
                    field.name
                )

                input_shape = (
                    guess.shape if len(guess.shape) > 1 else (guess.shape[0], 1)
                )

                if corresponding_parameter_value.shape != input_shape:
                    raise ValueError(
                        "The guess has the field "
                        + field.name
                        + " but its dimension does not match with the corresponding optimization variable"
                    )

                self._solver.set_value(corresponding_parameter_value, guess)
                continue

            composite_variable_guess = initial_guess.__getattribute__(field.name)

            if isinstance(composite_variable_guess, OptimizationObject):
                if not hasattr(corresponding_variable, field.name):
                    raise ValueError(
                        "The guess has the field "
                        + field.name
                        + " but it is not present in the optimization structure"
                    )

                self._set_initial_guess_internal(
                    initial_guess=composite_variable_guess,
                    corresponding_variable=corresponding_variable.__getattribute__(
                        field.name
                    ),
                )
                continue

            is_list = isinstance(composite_variable_guess, list)
            list_of_optimization_objects = is_list and all(
                isinstance(elem, OptimizationObject)
                for elem in composite_variable_guess
            )

            if list_of_optimization_objects:
                if not hasattr(corresponding_variable, field.name):
                    raise ValueError(
                        "The guess has the field "
                        + field.name
                        + " but it is not present in the optimization structure"
                    )
                corresponding_nested_variable = corresponding_variable.__getattribute__(
                    field.name
                )

                if not isinstance(corresponding_nested_variable, list):
                    raise ValueError(
                        "The guess has the field "
                        + field.name
                        + " as list, but the corresponding structure is not a list"
                    )

                i = 0
                for element in composite_variable_guess:
                    if i >= len(corresponding_nested_variable):
                        raise ValueError(
                            "The input guess is the list "
                            + field.name
                            + " but the corresponding variable structure is not a list"
                        )

                    self._set_initial_guess_internal(
                        initial_guess=element,
                        corresponding_variable=corresponding_nested_variable[i],
                    )
                    i += 1

    def generate_optimization_objects(
        self, input_structure: TOptimizationObject | List[TOptimizationObject], **kwargs
    ) -> TOptimizationObject | List[TOptimizationObject]:
        if isinstance(input_structure, OptimizationObject):
            return self._generate_objects_from_instance(input_structure=input_structure)
        return self._generate_objects_from_list(input_structure=input_structure)

    def get_optimization_objects(
        self,
    ) -> TOptimizationObject | List[TOptimizationObject]:
        return self._variables

    def register_problem(self, problem: Problem) -> None:
        self._problem = problem

    def get_problem(self) -> Problem:
        if self._problem is None:
            raise ProblemNotRegisteredException
        return self._problem

    def set_initial_guess(
        self, initial_guess: TOptimizationObject | List[TOptimizationObject]
    ) -> None:
        if isinstance(initial_guess, list):
            if not isinstance(self._variables, list):
                raise ValueError(
                    "The input guess is a list, but the specified variables structure is not"
                )

            i = 0
            for element in initial_guess:
                if i >= len(self._variables):
                    raise ValueError(
                        "The input guess is a list, but the specified variables structure is not"
                    )

                self._set_initial_guess_internal(
                    initial_guess=element, corresponding_variable=self._variables[i]
                )
                i += 1
            return

        self._set_initial_guess_internal(
            initial_guess=initial_guess, corresponding_variable=self._variables
        )

    def set_opti_options(
        self,
        inner_solver: str = None,
        options_solver: dict[str, Any] = None,
        options_plugin: dict[str, Any] = None,
    ) -> None:
        if inner_solver is not None:
            self._inner_solver = inner_solver
        if options_plugin is not None:
            self._options_plugin = options_plugin
        if options_solver is not None:
            self._options_solver = options_solver

        self._solver.solver(
            self._inner_solver, self._options_plugin, self._options_solver
        )

    def solve(self) -> None:
        self._solver.minimize(self._cost)
        # TODO Stefano: Consider solution state
        self._opti_solution = self._solver.solve()
        self._output_cost = self._opti_solution.value(self._cost)
        self._output_solution = self._generate_solution_output(self._variables)

    def get_values(self) -> TOptimizationObject | List[TOptimizationObject]:
        if self._output_solution is None:
            raise SolutionNotAvailableException
        return self._output_solution

    def get_cost_value(self) -> float:
        if self._output_cost is None:
            raise SolutionNotAvailableException
        return self._output_cost

    def add_cost(self, input_cost: cs.MX) -> None:
        if self._cost is None:
            self._cost = input_cost
            return

        self._cost += input_cost

    def add_constraint(self, input_constraint: cs.MX) -> None:
        self._solver.subject_to(input_constraint)

    def cost_function(self) -> cs.MX:
        return self._cost
