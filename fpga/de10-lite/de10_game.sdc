# 50 MHz DE10-Lite oscillator.
create_clock -name clk50 -period 20.000 [get_ports {MAX10_CLK1_50}]
derive_clock_uncertainty

# Board and PMOD inputs are asynchronous to the FPGA clock. The RTL contains
# the required gamepad synchronizers; these external paths have no STA clock.
set_false_path -from [get_ports {KEY[*]}]
set_false_path -from [get_ports {SW[*]}]
set_false_path -from [get_ports {gamepad_ui[*]}]

# External display and constant chip-select outputs.
set_false_path -to [get_ports {uo_out[*]}]
set_false_path -to [get_ports {flash_cen}]
set_false_path -to [get_ports {psram_b_cen}]

# QSPI PSRAM clock and half-cycle data relationship.
create_generated_clock \
    -name psram_sclk_out \
    -source [get_ports {MAX10_CLK1_50}] \
    -divide_by 2 \
    [get_ports {psram_sclk}]

set_multicycle_path -setup \
    -from [get_clocks {clk50}] \
    -to [get_ports {psram_sio[*] psram_a_cen}] 2
set_multicycle_path -hold \
    -from [get_clocks {clk50}] \
    -to [get_ports {psram_sio[*] psram_a_cen}] 1

set_multicycle_path -setup \
    -from [get_ports {psram_sio[*]}] \
    -to [get_clocks {clk50}] 2
set_multicycle_path -hold \
    -from [get_ports {psram_sio[*]}] \
    -to [get_clocks {clk50}] 1
