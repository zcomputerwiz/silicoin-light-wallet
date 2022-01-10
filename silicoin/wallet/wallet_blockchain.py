import logging
from typing import Dict, Optional, Tuple, List
from silicoin.consensus.block_header_validation import validate_finished_header_block
from silicoin.consensus.block_record import BlockRecord
from silicoin.consensus.blockchain import ReceiveBlockResult
from silicoin.consensus.blockchain_interface import BlockchainInterface
from silicoin.consensus.constants import ConsensusConstants
from silicoin.consensus.find_fork_point import find_fork_point_in_chain
from silicoin.consensus.full_block_to_block_record import block_to_block_record
from silicoin.types.blockchain_format.sized_bytes import bytes32
from silicoin.types.header_block import HeaderBlock
from silicoin.types.weight_proof import WeightProof
from silicoin.util.errors import Err
from silicoin.util.ints import uint32, uint64, uint128
from silicoin.wallet.key_val_store import KeyValStore
from silicoin.wallet.wallet_weight_proof_handler import WalletWeightProofHandler
from silicoin.consensus.pos_quality import UI_ACTUAL_SPACE_CONSTANT_FACTOR
from decimal import Decimal
from blspy import G1Element

log = logging.getLogger(__name__)


class WalletBlockchain(BlockchainInterface):
    constants: ConsensusConstants
    _basic_store: KeyValStore
    _weight_proof_handler: WalletWeightProofHandler

    synced_weight_proof: Optional[WeightProof]

    _peak: Optional[HeaderBlock]
    _height_to_hash: Dict[uint32, bytes32]
    _block_records: Dict[bytes32, BlockRecord]
    _latest_timestamp: uint64
    _sub_slot_iters: uint64
    _difficulty: uint64
    CACHE_SIZE: int
    stakings: Dict[bytes, uint64] = {}

    @staticmethod
    async def create(
        _basic_store: KeyValStore, constants: ConsensusConstants, weight_proof_handler: WalletWeightProofHandler
    ):
        """
        Initializes a blockchain with the BlockRecords from disk, assuming they have all been
        validated. Uses the genesis block given in override_constants, or as a fallback,
        in the consensus constants config.
        """
        self = WalletBlockchain()
        self._basic_store = _basic_store
        self.constants = constants
        self.CACHE_SIZE = constants.SUB_EPOCH_BLOCKS + 100
        self._weight_proof_handler = weight_proof_handler
        self.synced_weight_proof = await self._basic_store.get_object("SYNCED_WEIGHT_PROOF", WeightProof)
        self._peak = None
        self._peak = await self.get_peak_block()
        self._latest_timestamp = uint64(0)
        self._height_to_hash = {}
        self._block_records = {}
        if self.synced_weight_proof is not None:
            await self.new_weight_proof(self.synced_weight_proof)
        else:
            self._sub_slot_iters = constants.SUB_SLOT_ITERS_STARTING
            self._difficulty = constants.DIFFICULTY_STARTING

        return self

    async def new_weight_proof(self, weight_proof: WeightProof, records: Optional[List[BlockRecord]] = None) -> None:
        peak: Optional[HeaderBlock] = await self.get_peak_block()

        if peak is not None and weight_proof.recent_chain_data[-1].weight <= peak.weight:
            # No update, don't change anything
            return None
        self.synced_weight_proof = weight_proof
        await self._basic_store.set_object("SYNCED_WEIGHT_PROOF", weight_proof)

        latest_timestamp = self._latest_timestamp

        if records is None:
            success, _, _, records = await self._weight_proof_handler.validate_weight_proof(weight_proof, True)
            assert success
        assert records is not None and len(records) > 1

        for record in records:
            self._height_to_hash[record.height] = record.header_hash
            self.add_block_record(record)
            if record.is_transaction_block:
                assert record.timestamp is not None
                if record.timestamp > latest_timestamp:
                    latest_timestamp = record.timestamp

        self._sub_slot_iters = records[-1].sub_slot_iters
        self._difficulty = uint64(records[-1].weight - records[-2].weight)
        await self.set_peak_block(weight_proof.recent_chain_data[-1], latest_timestamp)
        self.clean_block_records()

    async def receive_block(self, block: HeaderBlock) -> Tuple[ReceiveBlockResult, Optional[Err]]:
        if self.contains_block_in_peak_chain(block.header_hash):
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK, None
        if not self.contains_block(block.prev_header_hash) and block.height > 0:
            return ReceiveBlockResult.DISCONNECTED_BLOCK, None
        if (
            len(block.finished_sub_slots) > 0
            and block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters is not None
        ):
            assert block.finished_sub_slots[0].challenge_chain.new_difficulty is not None  # They both change together
            sub_slot_iters: uint64 = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters
            difficulty: uint64 = block.finished_sub_slots[0].challenge_chain.new_difficulty
        else:
            sub_slot_iters = self._sub_slot_iters
            difficulty = self._difficulty
        required_iters, _, error = validate_finished_header_block(
            self.constants, self, block, False, difficulty, sub_slot_iters, False
        )
        if error is not None:
            return ReceiveBlockResult.INVALID_BLOCK, error.code
        if required_iters is None:
            return ReceiveBlockResult.INVALID_BLOCK, Err.INVALID_POSPACE

        block_record: BlockRecord = block_to_block_record(
            self.constants, self, required_iters, None, block, sub_slot_iters
        )
        self.add_block_record(block_record)
        if self._peak is None:
            if block_record.is_transaction_block:
                latest_timestamp = block_record.timestamp
            else:
                latest_timestamp = None
            self._height_to_hash[block_record.height] = block_record.header_hash
            await self.set_peak_block(block, latest_timestamp)
            return ReceiveBlockResult.NEW_PEAK, None
        elif block_record.weight > self._peak.weight:
            if block_record.prev_hash == self._peak.header_hash:
                fork_height: int = self._peak.height
            elif not self.contains_block_in_peak_chain(block_record.header_hash) and self.contains_block_in_peak_chain(
                block_record.prev_hash
            ):
                # special case
                fork_height = block_record.height - 1
            else:
                fork_height = find_fork_point_in_chain(self, block_record, self._peak)
            await self._rollback_to_height(fork_height)
            curr_record: BlockRecord = block_record
            latest_timestamp = self._latest_timestamp
            while curr_record.height > fork_height:
                self._height_to_hash[curr_record.height] = curr_record
                if curr_record.timestamp is not None and curr_record.timestamp > latest_timestamp:
                    latest_timestamp = curr_record.timestamp
                if curr_record.height == 0:
                    break
                curr_record = self.block_record(curr_record.prev_hash)
            self._sub_slot_iters = block_record.sub_slot_iters
            self._difficulty = uint64(block_record.weight - self.block_record(block_record.prev_hash).weight)
            await self.set_peak_block(block, latest_timestamp)
            self.clean_block_records()
            return ReceiveBlockResult.NEW_PEAK, None
        return ReceiveBlockResult.ADDED_AS_ORPHAN, None

    async def _rollback_to_height(self, height: int):
        if self._peak is None:
            return
        for h in range(max(0, height + 1), self._peak.height + 1):
            del self._height_to_hash[uint32(h)]

        await self._basic_store.remove_object("PEAK_BLOCK")

    def get_peak_height(self) -> uint32:
        if self._peak is None:
            return uint32(0)
        return self._peak.height

    async def set_peak_block(self, block: HeaderBlock, timestamp: Optional[uint64] = None):
        await self._basic_store.set_object("PEAK_BLOCK", block)
        self._peak = block
        if timestamp is not None:
            self._latest_timestamp = timestamp
        elif block.foliage_transaction_block is not None:
            self._latest_timestamp = block.foliage_transaction_block.timestamp
        log.info(f"Peak set to : {self._peak.height} timestamp: {self._latest_timestamp}")

    async def get_peak_block(self) -> Optional[HeaderBlock]:
        if self._peak is not None:
            return self._peak
        return await self._basic_store.get_object("PEAK_BLOCK", HeaderBlock)

    def get_latest_timestamp(self) -> uint64:
        return self._latest_timestamp

    def contains_block(self, header_hash: bytes32) -> bool:
        return header_hash in self._block_records

    def contains_height(self, height: uint32) -> bool:
        return height in self._height_to_hash

    def height_to_hash(self, height: uint32) -> bytes32:
        return self._height_to_hash[height]

    def try_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        if self.contains_block(header_hash):
            return self.block_record(header_hash)
        return None

    def contains_block_in_peak_chain(self, header_hash: bytes32) -> bool:
        "True if the header_hash is in current chain"
        block = self.try_block_record(header_hash)
        if block is None:
            return False
        return self._height_to_hash.get(block.height) == header_hash

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        return self._block_records[header_hash]

    def try_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        if self.contains_block(header_hash):
            return self.block_record(header_hash)
        return None


    def add_block_record(self, block_record: BlockRecord):
        self._block_records[block_record.header_hash] = block_record

    def clean_block_records(self):
        """
        Cleans the cache so that we only maintain relevant blocks. This removes
        block records that have height < peak - CACHE_SIZE.
        """
        height_limit = max(0, self.get_peak_height() - self.CACHE_SIZE)
        if len(self._block_records) < self.CACHE_SIZE:
            return None

        to_remove: List[bytes32] = []
        for header_hash, block_record in self._block_records.items():
            if block_record.height < height_limit:
                to_remove.append(header_hash)

        for header_hash in to_remove:
            del self._block_records[header_hash]

    async def get_network_space(self, newer: bytes32, older: bytes32) -> uint128:
        newer_block = await self.block_store.get_block_record(newer)
        if newer_block is None:
            raise ValueError("Newer block not found")
        older_block = await self.block_store.get_block_record(older)
        if older_block is None:
            raise ValueError("Newer block not found")
        delta_weight = newer_block.weight - older_block.weight

        delta_iters = newer_block.total_iters - older_block.total_iters
        weight_div_iters = delta_weight / delta_iters
        additional_difficulty_constant = self.constants.DIFFICULTY_CONSTANT_FACTOR
        eligible_plots_filter_multiplier = 2 ** self.constants.NUMBER_ZERO_BITS_PLOT_FILTER
        network_space_bytes_estimate = (
            UI_ACTUAL_SPACE_CONSTANT_FACTOR
            * weight_div_iters
            * additional_difficulty_constant
            * eligible_plots_filter_multiplier
        )
        return uint128(int(network_space_bytes_estimate))

    async def get_peak_network_space(self, block_range: int) -> uint128:
        peak = self.get_peak()

        if peak is not None and peak.height > 1:
            # Average over the last day
            older_header_hash = self.height_to_hash(uint32(max(1, peak.height - block_range)))
            assert older_header_hash is not None
            return await self.get_network_space(peak.header_hash, older_header_hash)
        else:
            return uint128(0)

    async def get_farmer_difficulty_coeff(
        self, farmer_public_key: G1Element, height: Optional[uint32] = None
    ) -> Decimal:
        return self.stakings.get(bytes(farmer_public_key), Decimal(20))
