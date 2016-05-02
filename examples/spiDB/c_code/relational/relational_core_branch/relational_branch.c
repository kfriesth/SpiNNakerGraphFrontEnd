#include "spin1_api.h"
#include <debug.h>
#include <simulation.h>
#include <circular_buffer.h>
#include <data_specification.h>

#include "common-typedefs.h"
#include "../../common/db-typedefs.h"
#include "../../common/sdp_utils.h"

//! data region definitions
typedef enum regions_e {
    SYSTEM_REGION = 0, SDP_PORT_REGION = 1, DB_DATA_REGION = 2
} regions_e;

//! callback priority levels
typedef enum callback_priority_e {
    SDP_MC_PRIORITY=0, USER_AND_TIMER_EVENT_PRIORITY = 2
} callback_priority_e;

//! elements within the sdp region
typedef enum sdp_port_region_elements_e {
    SDP_PORT_POSITION=0
} sdp_port_region_elements_e;

//! control value, which says how many timer ticks to run for before exiting
static uint32_t simulation_ticks = 0;
static uint32_t infinite_run = 0;
static uint32_t time = 0;

// sdp port data
uint32_t sdp_port_num = 0;

//! int as a bool to represent if this simulation should run forever
static uint32_t infinite_run;

//! hardcoded size of queues
static uint32_t QUEUE_SIZE = 128;

//Globals
static circular_buffer sdp_buffer;

//! core identification data
static uint32_t chip_x;
static uint32_t chip_y;
static uchar core;

//! state machine flag
static bool processing_events = false;

//! string rep of the core
id_t  my_id;

//! storage of sdp messages
sdp_msg_t** msg_copies;

//! position within the queue
uint queue_position = 0;

sdp_msg_t* send_response_msg(selectResponse* selResp,
                             uint32_t col_index){

    try(selResp);

    Table* table = selResp->table;
    id_t sel_id = selResp->id;
    address_t addr = selResp->addr;

    try(table && col_index > 0 && addr);

    uchar* col_name = table->cols[col_index].name;
    size_t data_size = table->cols[col_index].size;

    try(col_name && *col_name != 0 && data_size != 0);

    uchar pos = get_byte_pos(table, col_index) >> 2;

    sdp_msg_t* msg = create_sdp_header_to_host_alloc_extra(
                        sizeof(Response_hdr) + sizeof(Entry_hdr) + data_size);

    Response* r = (Response*)&msg->cmd_rc;
    r->id  = sel_id;
    r->cmd = SELECT;
    r->success = true;
    r->x = chip_x;
    r->y = chip_y;
    r->p = core;

    Entry* e = (Entry*)&(r->data);
    e->row_id = my_id << 24 | (uint32_t)addr;
    e->type   = table->cols[col_index].type;
    e->size   = (e->type == UINT32) ?
                 sizeof(uint32_t) : sark_str_len((char*)&addr[pos]);

    sark_word_cpy(e->col_name, col_name, MAX_COL_NAME_SIZE);
    sark_word_cpy(e->value, &addr[pos], e->size);

    log_info("Sending to host (%s,%s)", e->col_name, e->value);

    msg->length = sizeof(sdp_hdr_t) + sizeof(Response_hdr) +
                  sizeof(Entry_hdr) + e->size;

    if(!spin1_send_sdp_msg(msg, SDP_TIMEOUT)){
        log_error("Failed to send Response to host");
        return NULL;
    }

    return msg;
}

void breakInBlocks(selectResponse* selResp){

    if(selResp->n_cols == 0){ //wildcard '*'
        for(uchar i = 0; i < selResp->table->n_cols; i++){
            sdp_msg_t* msg = send_response_msg(selResp,i);
            if(!msg){
                log_info("Failed to send entry message...");
            }
            else{
                sark_delay_us(2);
                sark_free(msg);
            }
        }
    }
    else{ //columns specified
        for(uchar i = 0; i < selResp->n_cols; i++){
            sdp_msg_t* msg = send_response_msg(selResp,selResp->col_indices[i]);

            if(!msg){
                log_info("Failed to send entry message...");
            }
            else{
                sark_delay_us(2);
                sark_free(msg);
            }
        }
    }
}


void update(uint ticks, uint b){
    use(ticks);
    use(b);
    if ((infinite_run != TRUE) && (time >= simulation_ticks)) {
        log_info("Simulation complete.\n");

        // falls into the pause resume mode of operating
        simulation_handle_pause_resume(NULL);
        return;
    }
}

void sdp_packet_callback(uint mailbox, uint port) {
    use(port);

    queue_position = (queue_position+1)%QUEUE_SIZE;
    register sdp_msg_t* m = msg_copies[queue_position];
    sark_word_cpy(m, (sdp_msg_t*)mailbox, sizeof(sdp_hdr_t)+256);
    spin1_msg_free((sdp_msg_t*)mailbox);

    // If there was space, add packet to the ring buffer
    if (circular_buffer_add(sdp_buffer, (uint32_t)m)) {
        if (!processing_events) {
            processing_events = true;
            if(!spin1_trigger_user_event(0, 0)){
                log_error("Unable to trigger user event.");
            }
        }
    }
    else{
        log_error("Unable to add SDP packet to circular buffer.");
    }
}

void process_requests(uint arg0, uint arg1){
    use(arg0);
    use(arg1);

    uint32_t mailbox;
    uint i = 0;
    do {
        if (circular_buffer_get_next(sdp_buffer, &mailbox)) {
            if(++i > 1){
                log_info("i is %d", i);
            }

            sdp_msg_t* msg = (sdp_msg_t*)mailbox;

            spiDBQueryHeader* header = (spiDBQueryHeader*) &msg->cmd_rc;

            switch(header->cmd){
                case SELECT_RESPONSE:;
                    selectResponse* selResp = (selectResponse*)header;
                    log_info("SELECT_RESPONSE on '%s' with addr %08x from core %d",
                             selResp->table->name, selResp->addr, get_srce_core(msg));
                    breakInBlocks(selResp);
                    break;
                default:;
                    //log_info("[Warning] cmd not recognized: %d with id %d",
                    //         header->cmd, header->id);
                    break;
            }
        }
        else {
            processing_events = false;
        }
    }while (processing_events);
}

void receive_MC_data(uint key, uint payload)
{
    use(key);
    use(payload);
    log_error("Received unexpected MC packet with key=%d, payload=%08x",
              key, payload);
}

void receive_MC_void (uint key, uint unknown){
    use(key);
    use(unknown);
    log_error("Received unexpected MC packet with key=%d, no payload", key);
}

void c_main()
{
    chip_x = (spin1_get_chip_id() & 0xFF00) >> 8;
    chip_y = spin1_get_chip_id() & 0x00FF;
    core  = spin1_get_core_id();

    my_id  = chip_x << 16 | chip_y << 8 | core;

    log_info("Initializing Branch (%d,%d,%d)\n", chip_x, chip_y, core);

    msg_copies = (sdp_msg_t**)sark_alloc(QUEUE_SIZE, sizeof(sdp_msg_t*));
    for(uint i = 0; i < QUEUE_SIZE; i++){
        msg_copies[i] = (sdp_msg_t*)sark_alloc(1, sizeof(sdp_hdr_t)+256);
    }

    if(!msg_copies){
        log_error("Unable to allocate memory for msg_copies");
        rt_error(RTE_SWERR);
    }

    sdp_buffer = circular_buffer_initialize(QUEUE_SIZE);

    if(!sdp_buffer){
        rt_error(RTE_SWERR);
    }

    // Get the address this core's DTCM data starts at from SRAM
    address_t address = data_specification_get_data_address();

    log_info("DataSpecification address is %08x", address);

    // Read the header
    if (!data_specification_read_header(address)) {
        log_error("Could not read DataSpecification header");
        rt_error(RTE_SWERR);
    }

    // check system region
    address_t system_region =
        data_specification_get_region(SYSTEM_REGION, address);

    // timer period
    uint32_t timer_period = 0;

    if (!simulation_read_timing_details(
            system_region, APPLICATION_NAME_HASH, &timer_period)) {
        log_error("failed to read the system header");
        rt_error(RTE_SWERR);
    }

    spin1_set_timer_tick(timer_period);

    // Set up callback listening to SDP messages
    simulation_register_simulation_sdp_callback(
        &simulation_ticks, &infinite_run, SDP_MC_PRIORITY);

    // register callbacks
    spin1_sdp_callback_on(sdp_port_num, sdp_packet_callback, SDP_MC_PRIORITY);
    spin1_callback_on(USER_EVENT, process_requests,
                      USER_AND_TIMER_EVENT_PRIORITY);
    spin1_callback_on(TIMER_TICK, update, USER_AND_TIMER_EVENT_PRIORITY);

    spin1_callback_on(MCPL_PACKET_RECEIVED, receive_MC_data, SDP_MC_PRIORITY);
    spin1_callback_on(MC_PACKET_RECEIVED,   receive_MC_void, SDP_MC_PRIORITY);

    simulation_run();
}