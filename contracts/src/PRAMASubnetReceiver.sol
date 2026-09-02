// SPDX-License-Identifier: MIT
pragma solidity ^0.8.34;

/// @notice Minimal Telegraph ERC-8183 callback receipt. It retains only the
/// deterministic ABI commitment of a successful OnChainData response.
contract PRAMASubnetReceiver {
    struct OnChainData {
        address[] addresses;
        uint256[] integers;
        string[] strings;
        bool[] bools;
    }

    error Unauthorized();

    address public immutable TELEGRAPH_DIAMOND;
    mapping(uint256 => bytes32) public responseHash;

    constructor(address telegraphDiamond) {
        TELEGRAPH_DIAMOND = telegraphDiamond;
    }

    function subnetMessage(
        uint256 jobId,
        bool,
        OnChainData calldata response,
        string calldata
    ) external {
        if (msg.sender != TELEGRAPH_DIAMOND) revert Unauthorized();
        responseHash[jobId] = keccak256(abi.encode(response));
    }
}
