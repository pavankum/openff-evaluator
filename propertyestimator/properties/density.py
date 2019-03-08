"""
A collection of density physical property definitions.
"""

from propertyestimator.datasets.plugins import register_thermoml_property
from propertyestimator.properties.plugins import register_estimable_property
from propertyestimator.properties.properties import PhysicalProperty
from propertyestimator.properties.utils import generate_base_reweighting_protocols
from propertyestimator.thermodynamics import Ensemble
from propertyestimator.utils.statistics import ObservableType
from propertyestimator.workflow import WorkflowSchema
from propertyestimator.workflow import protocols, groups
from propertyestimator.workflow.schemas import WorkflowOutputToStore
from propertyestimator.workflow.utils import ProtocolPath


@register_estimable_property()
@register_thermoml_property(thermoml_string='Mass density, kg/m3')
class Density(PhysicalProperty):
    """A class representation of a density property"""

    @property
    def multi_component_property(self):
        """Returns whether this property is dependant on properties of the
        full mixed substance, or whether it is also dependant on the properties
        of the individual components also.
        """
        return False

    @staticmethod
    def get_default_workflow_schema(calculation_layer):
        """Returns the default workflow schema to use for
        a specific calculation layer.

        Parameters
        ----------
        calculation_layer: str
            The calculation layer which will attempt to execute the workflow
            defined by this schema.

        Returns
        -------
        WorkflowSchema
            The default workflow schema.
        """
        if calculation_layer == 'SimulationLayer':
            return Density.get_default_simulation_workflow_schema()
        elif calculation_layer == 'ReweightingLayer':
            return Density.get_default_reweighting_workflow_schema()

        return None

    @staticmethod
    def get_default_simulation_workflow_schema():

        schema = WorkflowSchema(property_type=Density.__name__)
        schema.id = '{}{}'.format(Density.__name__, 'Schema')

        # Initial coordinate and topology setup.
        build_coordinates = protocols.BuildCoordinatesPackmol('build_coordinates')

        build_coordinates.substance = ProtocolPath('substance', 'global')

        schema.protocols[build_coordinates.id] = build_coordinates.schema

        assign_topology = protocols.BuildSmirnoffSystem('build_topology')

        assign_topology.force_field_path = ProtocolPath('force_field_path', 'global')

        assign_topology.coordinate_file_path = ProtocolPath('coordinate_file_path', build_coordinates.id)
        assign_topology.substance = ProtocolPath('substance', 'global')

        schema.protocols[assign_topology.id] = assign_topology.schema

        # Equilibration
        energy_minimisation = protocols.RunEnergyMinimisation('energy_minimisation')

        energy_minimisation.input_coordinate_file = ProtocolPath('coordinate_file_path', build_coordinates.id)
        energy_minimisation.system = ProtocolPath('system', assign_topology.id)

        schema.protocols[energy_minimisation.id] = energy_minimisation.schema

        npt_equilibration = protocols.RunOpenMMSimulation('npt_equilibration')

        npt_equilibration.ensemble = Ensemble.NPT

        npt_equilibration.steps = 100000  # Debug settings.
        npt_equilibration.output_frequency = 5000  # Debug settings.

        npt_equilibration.thermodynamic_state = ProtocolPath('thermodynamic_state', 'global')

        npt_equilibration.input_coordinate_file = ProtocolPath('output_coordinate_file', energy_minimisation.id)
        npt_equilibration.system = ProtocolPath('system', assign_topology.id)

        schema.protocols[npt_equilibration.id] = npt_equilibration.schema

        # Production
        npt_production = protocols.RunOpenMMSimulation('npt_production')

        npt_production.ensemble = Ensemble.NPT

        npt_production.steps = 500000  # Debug settings.
        npt_production.output_frequency = 5000  # Debug settings.

        npt_production.thermodynamic_state = ProtocolPath('thermodynamic_state', 'global')

        npt_production.input_coordinate_file = ProtocolPath('output_coordinate_file', npt_equilibration.id)
        npt_production.system = ProtocolPath('system', assign_topology.id)

        # Analysis
        extract_density = protocols.ExtractAverageStatistic('extract_density')

        extract_density.statistics_type = ObservableType.Density
        extract_density.statistics_path = ProtocolPath('statistics_file_path', npt_production.id)

        # Set up a conditional group to ensure convergence of uncertainty
        converge_uncertainty = groups.ConditionalGroup('converge_uncertainty')
        converge_uncertainty.add_protocols(npt_production, extract_density)

        condition = groups.ConditionalGroup.Condition()

        condition.left_hand_value = ProtocolPath('value.uncertainty',
                                                 converge_uncertainty.id,
                                                 extract_density.id)

        condition.right_hand_value = ProtocolPath('target_uncertainty', 'global')

        condition.condition_type = groups.ConditionalGroup.ConditionType.LessThan

        converge_uncertainty.add_condition(condition)

        converge_uncertainty.max_iterations = 1

        schema.protocols[converge_uncertainty.id] = converge_uncertainty.schema

        # Finally, extract uncorrelated data
        extract_uncorrelated_trajectory = protocols.ExtractUncorrelatedTrajectoryData('extract_traj')

        extract_uncorrelated_trajectory.statistical_inefficiency = ProtocolPath('statistical_inefficiency',
                                                                                converge_uncertainty.id,
                                                                                extract_density.id)

        extract_uncorrelated_trajectory.equilibration_index = ProtocolPath('equilibration_index',
                                                                           converge_uncertainty.id,
                                                                           extract_density.id)

        extract_uncorrelated_trajectory.input_coordinate_file = ProtocolPath('output_coordinate_file',
                                                                             converge_uncertainty.id,
                                                                             npt_production.id)

        extract_uncorrelated_trajectory.input_trajectory_path = ProtocolPath('trajectory_file_path',
                                                                             converge_uncertainty.id,
                                                                             npt_production.id)

        schema.protocols[extract_uncorrelated_trajectory.id] = extract_uncorrelated_trajectory.schema

        extract_uncorrelated_statistics = protocols.ExtractUncorrelatedStatisticsData('extract_stats')

        extract_uncorrelated_statistics.statistical_inefficiency = ProtocolPath('statistical_inefficiency',
                                                                                converge_uncertainty.id,
                                                                                extract_density.id)

        extract_uncorrelated_statistics.equilibration_index = ProtocolPath('equilibration_index',
                                                                           converge_uncertainty.id,
                                                                           extract_density.id)

        extract_uncorrelated_statistics.input_statistics_path = ProtocolPath('statistics_file_path',
                                                                             converge_uncertainty.id,
                                                                             npt_production.id)

        schema.protocols[extract_uncorrelated_statistics.id] = extract_uncorrelated_statistics.schema

        # Define where the final values come from.
        schema.final_value_source = ProtocolPath('value', converge_uncertainty.id, extract_density.id)

        output_to_store = WorkflowOutputToStore()

        output_to_store.trajectory_file_path = ProtocolPath('output_trajectory_path',
                                                            extract_uncorrelated_trajectory.id)
        output_to_store.coordinate_file_path = ProtocolPath('output_coordinate_file',
                                                            converge_uncertainty.id, npt_production.id)

        output_to_store.statistics_file_path = ProtocolPath('output_statistics_path',
                                                            extract_uncorrelated_statistics.id)

        output_to_store.statistical_inefficiency = ProtocolPath('statistical_inefficiency', converge_uncertainty.id,
                                                                                            extract_density.id)

        schema.outputs_to_store = {'full_system': output_to_store}

        return schema

    @staticmethod
    def get_default_reweighting_workflow_schema():

        # The protocol which will be used to calculate the densities from
        # the existing data.
        density_calculation = protocols.ExtractAverageStatistic('calc_density_$(data_repl)')
        base_reweighting_protocols, data_replicator = generate_base_reweighting_protocols(density_calculation)

        density_calculation.statistics_type = ObservableType.Density
        density_calculation.statistics_path = ProtocolPath('statistics_file_path',
                                                           base_reweighting_protocols.unpack_stored_data.id)

        schema = WorkflowSchema(property_type=Density.__name__)
        schema.id = '{}{}'.format(Density.__name__, 'Schema')

        schema.protocols = {protocol.id: protocol.schema for protocol in base_reweighting_protocols}
        schema.replicators = [data_replicator]

        schema.final_value_source = ProtocolPath('value', base_reweighting_protocols.mbar_protocol.id)

        return schema
