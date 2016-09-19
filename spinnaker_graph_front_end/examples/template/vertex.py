from pacman.model.decorators.overrides import overrides
from spinn_front_end_common.abstract_models.impl.machine_data_specable_vertex\
    import MachineDataSpecableVertex
from spinn_front_end_common.abstract_models.abstract_has_associated_binary\
    import AbstractHasAssociatedBinary
from spinn_front_end_common.abstract_models\
    .abstract_binary_uses_simulation_run import AbstractBinaryUsesSimulationRun
from pacman.model.graphs.machine.impl.machine_vertex \
    import MachineVertex
from pacman.model.resources.cpu_cycles_per_tick_resource import \
    CPUCyclesPerTickResource
from pacman.model.resources.dtcm_resource import DTCMResource
from pacman.model.resources.resource_container import ResourceContainer
from pacman.model.resources.sdram_resource import SDRAMResource

from spinn_front_end_common.interface.buffer_management.\
    buffer_models.receives_buffers_to_host_basic_impl import \
    ReceiveBuffersToHostBasicImpl
from spinn_front_end_common.utilities import constants
from spinn_front_end_common.interface.simulation import simulation_utilities
from spinnaker_graph_front_end.utilities.conf import config

from enum import Enum

import logging

logger = logging.getLogger(__name__)

PARTITION_ID = "DATA"


class Vertex(
        MachineVertex, MachineDataSpecableVertex, AbstractHasAssociatedBinary,
        ReceiveBuffersToHostBasicImpl, AbstractBinaryUsesSimulationRun):

    # The number of bytes for the has_key flag and the key
    TRANSMISSION_REGION_N_BYTES = 2 * 4

    # TODO: Update with the regions of the application
    DATA_REGIONS = Enum(
        value="DATA_REGIONS",
        names=[('SYSTEM', 0),
               ('TRANSMISSION', 1),
               ('RECORDED_DATA', 2),
               ('BUFFERED_STATE', 3)])

    def __init__(self, label, machine_time_step, time_scale_factor,
                 constraints=None):

        self._recording_size = 5000

        MachineVertex.__init__(self, label=label, constraints=constraints)
        ReceiveBuffersToHostBasicImpl.__init__(self)

        self.activate_buffering_output()

        self._buffer_size_before_receive = config.getint(
            "Buffers", "buffer_size_before_receive")

        self._time_between_requests = config.getint(
            "Buffers", "time_between_requests")

        self.placement = None

    @overrides(MachineVertex.resources_required)
    def resources_required(self):
        resources = ResourceContainer(
            cpu_cycles=CPUCyclesPerTickResource(45),
            dtcm=DTCMResource(100),
            sdram=SDRAMResource(
                constants.SYSTEM_BYTES_REQUIREMENT +
                self.TRANSMISSION_REGION_N_BYTES +
                self.get_buffer_state_region_size(1) +
                self.get_recording_data_size(1) + self._recording_size))
        resources.extend(self.get_extra_resources(
            config.get("Buffers", "receive_buffer_host"),
            config.getint("Buffers", "receive_buffer_port")))

    @overrides(AbstractHasAssociatedBinary.get_binary_file_name)
    def get_binary_file_name(self):
        return "c_code.aplx"

    @overrides(MachineDataSpecableVertex.generate_machine_data_specification)
    def generate_machine_data_specification(
            self, spec, placement, machine_graph, routing_info, iptags,
            reverse_iptags, machine_time_step, time_scale_factor):
        """ Generate data

        :param placement: the placement object for the dsg
        :param machine_graph: the graph object for this dsg
        :param routing_info: the routing info object for this dsg
        :param ip_tags: the collection of iptags generated by the tag allocator
        :param reverse_iptags: the collection of reverse iptags generated by\
                the tag allocator
        """
        self.placement = placement

        # Create the data regions
        self._reserve_memory_regions(spec)

        # write simulation interface data
        spec.switch_write_focus(self.DATA_REGIONS.SYSTEM.value)
        spec.write_array(simulation_utilities.get_simulation_header_array(
            self.get_binary_file_name(), machine_time_step,
            time_scale_factor))

        # write recording data interface
        self.write_recording_data(
            spec, iptags, [self._recording_size],
            self._buffer_size_before_receive, self._time_between_requests)

        # Get the key, assuming all outgoing edges use the same key
        has_key = 0
        key = routing_info.get_first_key_from_pre_vertex(self, PARTITION_ID)
        if key is None:
            key = 0
        else:
            has_key = 1

        # Write the transmission region
        spec.switch_write_focus(self.DATA_REGIONS.TRANSMISSION.value)
        spec.write_value(has_key)
        spec.write_value(key)

        # End-of-Spec:
        spec.end_specification()

    def _reserve_memory_regions(self, spec):
        spec.reserve_memory_region(
            region=self.DATA_REGIONS.SYSTEM.value,
            size=constants.SYSTEM_BYTES_REQUIREMENT,
            label='systemInfo')
        spec.reserve_memory_region(
            region=self.DATA_REGIONS.TRANSMISSION.value,
            seiz=self.TRANSMISSION_REGION_N_BYTES, label="transmission")
        self.reserve_buffer_regions(
            spec, self.DATA_REGIONS.BUFFERED_STATE.value,
            [self.DATA_REGIONS.RECORDED_DATA.value],
            [self._recording_size])

    def read(self, placement, buffer_manager):
        """ Get the recorded data

        :param placement: the location of this vertex
        :param buffer_manager: the buffer manager
        :return: The data read
        """
        data_pointer, is_missing_data = buffer_manager.get_data_for_vertex(
            placement, self.DATA_REGIONS.RECORDED_DATA.value,
            self.DATA_REGIONS.BUFFERED_STATE.value)
        if is_missing_data:
            logger.warn("Some data was lost when recording")
        record_raw = data_pointer.read_all()
        return record_raw
