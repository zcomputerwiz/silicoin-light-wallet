from silicoin.types.blockchain_format.program import INFINITE_COST
from silicoin.types.spend_bundle import SpendBundle
from silicoin.types.generator_types import BlockGenerator
from silicoin.consensus.cost_calculator import calculate_cost_of_program, NPCResult
from silicoin.consensus.default_constants import DEFAULT_CONSTANTS
from silicoin.full_node.bundle_tools import simple_solution_generator
from silicoin.full_node.mempool_check_conditions import get_name_puzzle_conditions


def cost_of_spend_bundle(spend_bundle: SpendBundle) -> int:
    program: BlockGenerator = simple_solution_generator(spend_bundle)
    npc_result: NPCResult = get_name_puzzle_conditions(
        program, INFINITE_COST, cost_per_byte=DEFAULT_CONSTANTS.COST_PER_BYTE, safe_mode=True
    )
    cost: int = calculate_cost_of_program(program.program, npc_result, DEFAULT_CONSTANTS.COST_PER_BYTE)
    return cost
