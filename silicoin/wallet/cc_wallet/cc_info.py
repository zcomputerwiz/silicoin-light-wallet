from dataclasses import dataclass
from typing import List, Optional, Tuple

from silicoin.types.blockchain_format.program import Program
from silicoin.types.blockchain_format.sized_bytes import bytes32
from silicoin.wallet.lineage_proof import LineageProof
from silicoin.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class CCInfo(Streamable):
    limitations_program_hash: bytes32
    my_genesis_checker: Optional[Program]  # this is the program
    lineage_proofs: List[Tuple[bytes32, Optional[LineageProof]]]  # {coin.name(): lineage_proof}
