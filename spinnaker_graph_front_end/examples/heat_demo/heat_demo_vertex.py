
# dsg imports
from data_specification.enums.data_type import DataType

# pacman imports
from pacman.model.decorators.overrides import overrides
from pacman.model.graphs.machine.impl.machine_vertex \
    import MachineVertex
from pacman.model.resources.cpu_cycles_per_tick_resource import \
    CPUCyclesPerTickResource
from pacman.model.resources.dtcm_resource import DTCMResource
from pacman.model.resources.resource_container import ResourceContainer
from pacman.model.resources.sdram_resource import SDRAMResource

# graph front end imports
from .heat_demo_edge import HeatDemoEdge
from spinnaker_graph_front_end.utilities.conf import config

# FEC imports
from spinn_front_end_common.abstract_models\
    .abstract_binary_uses_simulation_run import AbstractBinaryUsesSimulationRun
from spinn_front_end_common.interface.simulation import simulation_utilities
from spinn_front_end_common.utility_models.live_packet_gather import \
    LivePacketGather
from spinn_front_end_common.utility_models.\
    reverse_ip_tag_multi_cast_source import ReverseIpTagMultiCastSource
from spinn_front_end_common.utilities import constants
from spinn_front_end_common.utilities import exceptions
from spinn_front_end_common.abstract_models.impl.machine_data_specable_vertex \
    import MachineDataSpecableVertex
from spinn_front_end_common.abstract_models.abstract_has_associated_binary \
    import AbstractHasAssociatedBinary

# general imports
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class HeatDemoVertex(
        MachineVertex, MachineDataSpecableVertex, AbstractHasAssociatedBinary,
        AbstractBinaryUsesSimulationRun):
    """ A vertex partition for a heat demo; represents a heat element.
    """

    CORE_APP_IDENTIFIER = 0xABCD

    # Regions for populations
    DATA_REGIONS = Enum(
        value="DATA_REGIONS",
        names=[('SYSTEM', 0),
               ('TRANSMISSIONS', 1),
               ('NEIGHBOUR_KEYS', 2),
               ('COMMAND_KEYS', 3),
               ('TEMP_VALUE', 4)])

    # one key for each incoming edge.
    NEIGHBOUR_DATA_SIZE = 10 * 4
    TRANSMISSION_DATA_SIZE = 2 * 4
    COMMAND_KEYS_SIZE = 3 * 4
    TEMP_VALUE_SIZE = 1 * 4

    _model_based_max_atoms_per_core = 1
    _model_n_atoms = 1

    def __init__(self, label, machine_time_step, time_scale_factor,
                 heat_temperature=0, constraints=None):

        # resources used by a heat element vertex
        sdram = SDRAMResource(
            23 + config.getint("Buffers", "minimum_buffer_sdram"))
        self._resources = \
            ResourceContainer(cpu_cycles=CPUCyclesPerTickResource(45),
                              dtcm=DTCMResource(34), sdram=sdram)

        MachineVertex.__init__(self, label=label, constraints=constraints)

        # app specific data items
        self._heat_temperature = heat_temperature
        self._time_between_requests = config.getint(
            "Buffers", "time_between_requests")

    @property
    @overrides(MachineVertex.resources_required)
    def resources_required(self):
        return self._resources

    @overrides(AbstractHasAssociatedBinary.get_binary_file_name)
    def get_binary_file_name(self):
        """

        :return:
        """
        return "heat_demo.aplx"

    @overrides(MachineDataSpecableVertex.generate_machine_data_specification)
    def generate_machine_data_specification(
            self, spec, placement, machine_graph, routing_info, iptags,
            reverse_iptags, machine_time_step, time_scale_factor):
        """

        :param placement: the placement object for the dsg
        :param machine_graph: the graph object for this dsg
        :param routing_info: the routing info object for this dsg
        :param iptags: the collection of iptags generated by the tag allocator
        :param reverse_iptags: the collection of reverse iptags generated by\
                the tag allocator
        :param spec: the writer interface
        """

        # Setup words + 1 for flags + 1 for recording size
        setup_size = constants.SYSTEM_BYTES_REQUIREMENT

        spec.comment("\n*** Spec for SpikeSourceArray Instance ***\n\n")

        # ###################################################################
        # Reserve SDRAM space for memory areas:

        spec.comment("\nReserving memory space for spike data region:\n\n")

        # Create the data regions for the spike source array:
        self._reserve_memory_regions(spec, setup_size)

        # handle simulation.c items
        spec.switch_write_focus(self.DATA_REGIONS.SYSTEM.value)
        spec.write_array(simulation_utilities.get_simulation_header_array(
            self.get_binary_file_name(), machine_time_step,
            time_scale_factor))

        # application specific data items
        self._write_transmission_keys(spec, routing_info, machine_graph)
        self._write_key_data(spec, routing_info, machine_graph)
        self._write_temp_data(spec)

        # End-of-Spec:
        spec.end_specification()

    def _write_temp_data(self, spec):
        spec.switch_write_focus(region=self.DATA_REGIONS.TEMP_VALUE.value)
        spec.comment("writing initial temp for this heat element \n")
        spec.write_value(data=self._heat_temperature)

    def _reserve_memory_regions(self, spec, system_size):
        """

        :param spec:
        :param system_size:
        :return:
        """
        spec.reserve_memory_region(
            region=self.DATA_REGIONS.SYSTEM.value,
            size=system_size, label='systemInfo')
        spec.reserve_memory_region(
            region=self.DATA_REGIONS.TRANSMISSIONS.value,
            size=self.TRANSMISSION_DATA_SIZE, label="inputs")
        spec.reserve_memory_region(
            region=self.DATA_REGIONS.NEIGHBOUR_KEYS.value,
            size=self.NEIGHBOUR_DATA_SIZE, label="inputs")
        spec.reserve_memory_region(
            region=self.DATA_REGIONS.COMMAND_KEYS.value,
            size=self.COMMAND_KEYS_SIZE, label="commands")
        spec.reserve_memory_region(
            region=self.DATA_REGIONS.TEMP_VALUE.value,
            size=self.TEMP_VALUE_SIZE, label="temp")

    def _write_transmission_keys(self, spec, routing_info, graph):
        """

        :param spec:
        :param routing_info:
        :param graph:
        :return:
        """

        # Every edge should have the same key
        partitions = graph.get_outgoing_edge_partitions_starting_at_vertex(
            self)
        for partition in partitions:
            key = routing_info.get_first_key_from_partition(partition)
            spec.switch_write_focus(
                region=self.DATA_REGIONS.TRANSMISSIONS.value)

            # Write Key info for this core:
            if key is None:

                # if there's no key, then two false's will cover it.
                spec.write_value(data=0)
                spec.write_value(data=0)

            else:

                # has a key, thus set has key to 1 and then add key
                spec.write_value(data=1)
                spec.write_value(data=key)

    def _write_key_data(self, spec, routing_info, graph):
        """

        :param spec:
        :param routing_info:
        :param graph:
        :return:
        """
        spec.switch_write_focus(region=self.DATA_REGIONS.NEIGHBOUR_KEYS.value)

        # get incoming edges
        incoming_edges = graph.get_edges_ending_at_vertex(self)
        spec.comment("\n the keys for the neighbours in EAST, NORTH, WEST, "
                     "SOUTH. order:\n\n")
        direction_edges = list()
        fake_temp_edges = list()
        command_edge = None
        output_edge = None
        for incoming_edge in incoming_edges:
            if (isinstance(incoming_edge, HeatDemoEdge) and
                    isinstance(incoming_edge.pre_vertex,
                               ReverseIpTagMultiCastSource)):
                fake_temp_edges.append(incoming_edge)
            elif (isinstance(incoming_edge, HeatDemoEdge) and
                    isinstance(incoming_edge.pre_vertex,
                               HeatDemoVertex)):
                direction_edges.append(incoming_edge)

        out_going_edges = graph.get_edges_starting_at_vertex(self)
        for out_going_edge in out_going_edges:
            if isinstance(out_going_edge.post_vertex, LivePacketGather):
                if output_edge is not None:
                    raise exceptions.ConfigurationException(
                        "already found a outgoing edge."
                        " Can't have more than one!")
                output_edge = out_going_edge

        direction_edges = {
            edge.direction.value: edge for edge in direction_edges
        }

        # write each key that this module should expect packets from in order
        # of EAST, NORTH, WEST, SOUTH.
        loaded_keys = 0
        for current_direction in range(4):
            edge = direction_edges.get(current_direction, None)
            if edge is not None:
                key = routing_info.get_first_key_for_edge(edge)
                spec.write_value(data=key)
                loaded_keys += 1
            else:
                spec.write_value(data_type=DataType.INT32, data=-1)

        if loaded_keys == 0:
            raise exceptions.ConfigurationException(
                "This heat element  {} does not receive any data from other "
                "elements. Please fix and try again.  It currently has"
                " incoming edges of {} directional edges of {} and fake edges"
                " of {} and command edge of {} and output edge of {}"
                .format(self.label, incoming_edges, direction_edges,
                        fake_temp_edges, command_edge, output_edge))

        # write each key that this model should expect packets from in order of
        # EAST, NORTH, WEST, SOUTH for injected temperatures
        fake_temp_edges = {
            edge.direction.value: edge for edge in fake_temp_edges
        }
        current_direction = 0
        for current_direction in range(4):
            edge = fake_temp_edges.get(current_direction, None)
            if edge is not None:
                key = routing_info.get_first_key_for_edge(edge)
                spec.write_value(data=key)
            else:
                spec.write_value(data_type=DataType.INT32, data=-1)

        # write keys for commands
        spec.switch_write_focus(region=self.DATA_REGIONS.COMMAND_KEYS.value)
        spec.comment(
            "\n the command keys in order of STOP, PAUSE, RESUME:\n\n")
        commands_keys_and_masks = \
            routing_info.get_routing_info_for_edge(command_edge)

        # get just the keys
        keys = list()
        if commands_keys_and_masks is not None:
            for key_and_mask in commands_keys_and_masks:
                keys_given, _ = key_and_mask.get_keys(n_keys=3)
                keys.extend(keys_given)
            # sort keys in ascending order
            keys = sorted(keys, reverse=False)
            if len(keys) != 3:
                raise exceptions.ConfigurationException(
                    "Do not have enough keys to reflect the commands. broken."
                    "There are {} keys instead of 3".format(len(keys)))
            for key in keys:
                spec.write_value(data=key)
        else:
            for _ in range(0, 3):
                spec.write_value(data_type=DataType.INT32, data=-1)
            logger.warn(
                "Set up to not use commands. If commands are needed, "
                "Please create a command sender and wire it to this vertex.")
