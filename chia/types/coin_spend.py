from dataclasses import dataclass
from typing import List

from blspy import G2Element
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram, INFINITE_COST
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.chain_utils import additions_for_solution, fee_for_solution
from chia.util.puzzle_compression import KnownPuzzles, PuzzleRepresentation
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class CoinSpend(Streamable):
    """
    This is a rather disparate data structure that validates coin transfers. It's generally populated
    with data from different sources, since burned coins are identified by name, so it is built up
    more often that it is streamed.
    """

    coin: Coin
    puzzle_reveal: SerializedProgram
    solution: SerializedProgram

    def additions(self) -> List[Coin]:
        return additions_for_solution(self.coin.name(), self.puzzle_reveal, self.solution, INFINITE_COST)

    def reserved_fee(self) -> int:
        return fee_for_solution(self.puzzle_reveal, self.solution, INFINITE_COST)

    def hints(self) -> List[bytes]:
        # import above was causing circular import issue
        from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
        from chia.consensus.default_constants import DEFAULT_CONSTANTS
        from chia.types.spend_bundle import SpendBundle
        from chia.full_node.bundle_tools import simple_solution_generator

        bundle = SpendBundle([self], G2Element())
        generator = simple_solution_generator(bundle)

        npc_result = get_name_puzzle_conditions(
            generator, INFINITE_COST, cost_per_byte=DEFAULT_CONSTANTS.COST_PER_BYTE, safe_mode=False
        )
        h_list = []
        for npc in npc_result.npc_list:
            for opcode, conditions in npc.conditions:
                if opcode == ConditionOpcode.CREATE_COIN:
                    for condition in conditions:
                        if len(condition.vars) > 2 and condition.vars[2] != b"":
                            h_list.append(condition.vars[2])

        return h_list

    """
    These compression methods should not be used for sending coin spends or putting them into blocks.
    They exist for the purpose of making stored puzzles (In a file or DB) smaller
    """

    @classmethod
    def compress(cls, coin_spend: "CoinSpend") -> "CoinSpend":
        _, new_puzzle_rep = KnownPuzzles.match_puzzle(coin_spend.puzzle_reveal.to_program())
        return cls(
            coin_spend.coin,
            Program.to(KnownPuzzles.serialize_and_version(new_puzzle_rep)).to_serialized_program(),
            coin_spend.solution,
        )

    @classmethod
    def decompress(cls, coin_spend: "CoinSpend") -> "CoinSpend":
        program = Program.to([])
        deversioned_bytes = KnownPuzzles.check_version(coin_spend.puzzle_reveal.to_program().as_python())
        try:
            program = PuzzleRepresentation.from_bytes(deversioned_bytes).construct()
        except Exception:
            program = Program.from_bytes(deversioned_bytes)

        return cls(
            coin_spend.coin,
            program.to_serialized_program(),
            coin_spend.solution,
        )
