# ------------------------------------------------------------------------------
# Part of Red Queen Project.  This file is distributed under the MIT License.
# See accompanying file /LICENSE for details.
# ------------------------------------------------------------------------------
from tweedledum.ir import Circuit
from tweedledum.target import Device
from tweedledum.passes import bridge_decomp, bridge_map, jit_map, sabre_map

from qiskit import QuantumCircuit
from qiskit.transpiler import CouplingMap
from qiskit.transpiler.passmanager import PassManager
from qiskit.transpiler.passes import ApplyLayout
from qiskit.transpiler.passes import CheckMap
from qiskit.transpiler.passes import VF2Layout
from qiskit.transpiler.passes import DenseLayout
from qiskit.transpiler.passes import EnlargeWithAncilla
from qiskit.transpiler.passes import FullAncillaAllocation
from qiskit.transpiler.passes import SabreLayout
from qiskit.transpiler.passes import SabreSwap
from qiskit.transpiler.passes import StochasticSwap


def _qiskit_pass_manager(
    layout_method, routing_method, coupling_map, seed_transpiler=1337
):
    coupling_map = CouplingMap(coupling_map)
    pm = PassManager()

    _swap = list()
    if routing_method == "sabre":
        _swap = [SabreSwap(coupling_map, heuristic="decay", seed=seed_transpiler)]
    elif routing_method == "stochastic":
        _swap = [StochasticSwap(coupling_map, trials=200, seed=seed_transpiler)]

    # Choose an initial layout
    _choose_layout_0 = VF2Layout(
        coupling_map,
        seed=seed_transpiler,
        call_limit=int(5e4),  # Set call limit to ~100ms with retworkx 0.10.2
        time_limit=0.1,
    )
    if layout_method == "sabre":
        _choose_layout_1 = SabreLayout(
            coupling_map, routing_pass=_swap[0], max_iterations=5, seed=seed_transpiler
        )
    elif layout_method == "dense":
        _choose_layout_1 = DenseLayout(coupling_map)

    def _choose_layout_condition(property_set):
        return not property_set["layout"]

    # Extend dag/layout with ancillae using the full coupling map
    _embed = [FullAncillaAllocation(coupling_map), EnlargeWithAncilla(), ApplyLayout()]

    _swap_check = CheckMap(coupling_map)

    def _swap_condition(property_set):
        return not property_set["is_swap_mapped"]

    # Build pass manager
    pm.append(_choose_layout_0, condition=_choose_layout_condition)
    pm.append(_choose_layout_1, condition=_choose_layout_condition)
    pm.append(_embed)
    pm.append(_swap_check)
    pm.append(_swap, condition=_swap_condition)
    return pm


def run_qiskit_mapper(benchmark, layout_method, routing_method, coupling_map, path):
    circuit = QuantumCircuit.from_qasm_file(str(path))
    pm = _qiskit_pass_manager(layout_method, routing_method, coupling_map)
    info, mapped_circuit = benchmark(pm.run, circuit)
    info.quality_stats["cx"] = 3 * mapped_circuit.count_ops().get("swap", 0)


def run_tweedledum_mapper(benchmark, routing_method, coupling_map, path):
    """Runs one of tweedledum's mappers on a circuit."""
    circuit = Circuit.from_qasm_file(str(path))
    device = Device.from_edge_list(coupling_map)
    if routing_method == "jit":
        info, [mapped_circuit, _] = benchmark(jit_map, device, circuit)
    elif routing_method == "sabre":
        info, [mapped_circuit, _] = benchmark(sabre_map, device, circuit)
    elif routing_method == "bridge":
        info, [mapped_circuit, _] = benchmark(bridge_map, device, circuit)
        mapped_circuit = bridge_decomp(device, mapped_circuit)
    swaps_cost = 0
    for instruction in mapped_circuit:
        if instruction.kind() == "std.swap":
            swaps_cost += 2
    info.quality_stats["cx"] = swaps_cost + len(mapped_circuit) - len(circuit)
