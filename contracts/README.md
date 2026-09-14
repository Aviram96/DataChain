# Datachain contracts (Hardhat 3)

Solidity sources and Hardhat tooling for on-chain anchoring (`ROADMAP.md`).

`Datachain.sol` records one-minute segment metadata (camera id, start/end, IPFS CID, SHA-256) so it can be read back later. The deployer address is the only writer.

## Stack

- **Hardhat 3** with **`@nomicfoundation/hardhat-toolbox-viem`** (Viem + **Node.js `node:test`** for TypeScript tests).
- **`"type": "module"`** in `package.json` — Hardhat 3 expects an **ESM** Node project.

## Prerequisites

- **Node.js 22+** (Hardhat 3 baseline).

## Commands

From this directory:

```bash
npm install
npm run compile
npm test
```

Equivalent: `npx hardhat compile`, `npx hardhat test`.

## Deploy to Polygon Amoy (Slice D / CP-D.P4)

**Testnet only** (chain id **80002**). Do not use a mainnet key. Fund the deployer with Amoy POL from a faucet.

1. Copy `.env.example` to `.env` (gitignored) and set `AMOY_PRIVATE_KEY`. Optionally set `AMOY_RPC_URL` to a provider if the public RPC is slow.
2. Load those variables in your shell, or use Hardhat’s encrypted keystore (`AMOY_RPC_URL`, `AMOY_PRIVATE_KEY` as config variables).
3. From `contracts/`:

```bash
npm run deploy:amoy
```

The script refuses any network other than `polygonAmoy` and checks chain id **80002**. It prints the contract address and an [Amoy Polygonscan](https://amoy.polygonscan.com/) link. Save the address for a later backend slice (`DATACHAIN_CONTRACT_ADDRESS`). This repo does not send a deploy transaction until you run that command.

PowerShell example:

```powershell
$env:AMOY_RPC_URL = "https://rpc-amoy.polygon.technology"
$env:AMOY_PRIVATE_KEY = "0xYOUR_TESTNET_KEY"
npm run deploy:amoy
```

## Dependency audits

After installing or bumping packages, run:

```bash
npm audit fix
```

Avoid **`npm audit fix --force`** unless you accept breaking upgrades across the toolchain. Review `npm audit` output periodically.

## Layout

| Path | Purpose |
| ---- | ------- |
| `contracts/` | `.sol` sources (Hardhat default inner folder) |
| `test/` | TypeScript tests (`node:test` + Viem) |
| `scripts/deploy.ts` | Polygon Amoy deploy |
| `hardhat.config.ts` | Compiler, `polygonAmoy` network |
| `.env.example` | `AMOY_RPC_URL` / `AMOY_PRIVATE_KEY` placeholders |
