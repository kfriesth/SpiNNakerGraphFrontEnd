from data_specification.file_data_writer import FileDataWriter

from pacman.model.abstract_classes.abstract_constrained_vertex \
    import AbstractConstrainedVertex

from spinn_front_end_common.utilities import exceptions

from abc import ABCMeta
from six import add_metaclass
from abc import abstractmethod

import tempfile
import os


@add_metaclass(ABCMeta)
class AbstractPartitionedDataSpecableVertex(object):

    @abstractmethod
    def generate_data_spec(
            self, placement, sub_graph, routing_info, hostname,  report_folder,
            write_text_specs, application_run_time_folder):
        """
        method to determine how to generate their data spec for a non neural
        application
        """

    @abstractmethod
    def get_binary_file_name(self):
        """
        method to return the binary name for a given dataspecable vertex
        """

    @property
    def machine_time_step(self):
        return self._machine_time_step

    @property
    def no_machine_time_steps(self):
        return self._no_machine_time_steps

    @property
    def application_run_time(self):
        return self._application_runtime

    def set_application_runtime(self, new_runtime):
        if self._application_runtime is None:
            self._application_runtime = new_runtime
        else:
            raise exceptions.ConfigurationException(
                "cannot set the runtime of a given model once it has"
                "already been set")

    def set_no_machine_time_steps(self, new_no_machine_time_steps):
        if self._no_machine_time_steps is None:
            self._no_machine_time_steps = new_no_machine_time_steps
        else:
            raise exceptions.ConfigurationException(
                "cannot set the number of machine time steps of a given"
                " model once it has already been set")

    @staticmethod
    def get_data_spec_file_writers(
            processor_chip_x, processor_chip_y, processor_id, hostname,
            report_directory, write_text_specs,
            application_run_time_report_folder):
        binary_file_path = \
            AbstractPartitionedDataSpecableVertex.get_data_spec_file_path(
                processor_chip_x, processor_chip_y, processor_id, hostname,
                application_run_time_report_folder)
        data_writer = FileDataWriter(binary_file_path)
        # check if text reports are needed and if so initilise the report
        # writer to send down to dsg
        report_writer = None
        if write_text_specs:
            new_report_directory = os.path.join(report_directory,
                                                "data_spec_text_files")
            if not os.path.exists(new_report_directory):
                os.mkdir(new_report_directory)

            file_name = "{}_dataSpec_{}_{}_{}.txt"\
                        .format(hostname, processor_chip_x, processor_chip_y,
                                processor_id)
            report_file_path = os.path.join(new_report_directory, file_name)
            report_writer = FileDataWriter(report_file_path)

        return data_writer, report_writer

    @staticmethod
    def get_data_spec_file_path(processor_chip_x, processor_chip_y,
                                processor_id, hostname,
                                application_run_time_folder):

        if application_run_time_folder == "TEMP":
            application_run_time_folder = tempfile.gettempdir()

        binary_file_path = \
            application_run_time_folder + os.sep + "{}_dataSpec_{}_{}_{}.dat"\
            .format(hostname, processor_chip_x, processor_chip_y, processor_id)
        return binary_file_path

    @staticmethod
    def get_application_data_file_path(
            processor_chip_x, processor_chip_y, processor_id, hostname,
            application_run_time_folder):

        if application_run_time_folder == "TEMP":
            application_run_time_folder = tempfile.gettempdir()

        application_data_file_name = application_run_time_folder + os.sep + \
            "{}_appData_{}_{}_{}.dat".format(hostname, processor_chip_x,
                                             processor_chip_y, processor_id)
        return application_data_file_name

    @staticmethod
    def get_mem_write_base_address(processor_id):
        return 0xe5007000 + 128 * processor_id + 112