# Cisco Catalyst 9800-CL Wireless Controller on GCP

This guide covers bringing up a current Cisco `C9800-CL` on Google Cloud Platform from Cisco's downloadable `qcow2`, confirming the controller is truly usable, and joining an AP in the supported public-cloud model.

Tested baseline:

- controller train: `17.15.04d`
- working outcome: SSH reachable, HTTPS / WebUI reachable, Day 0 wizard cleared, AP joined in `FlexConnect`, client traffic working

## Outcome

Use Cisco's downloadable `qcow2`, not Google Cloud Marketplace, as the baseline for a current `C9800-CL` on GCP.

The path that worked was:

1. patch the image so it actually takes Cisco's GCP bootstrap path
2. replace Cisco's broken raw-image custom-data decoder
3. preserve the first boot disk that gets the farthest
4. append the final Day 0 CLI directly into `/varied/iosxe_config.txt`
5. boot that preserved disk
6. fix management IP if DHCP does not land
7. set the wireless country code
8. join APs in `FlexConnect`, not `Local`

Important: the built-in GCP bootstrap path is not just convenience logic. It appears to create Cisco-specific bootstrap state that the controller expects on first boot. Direct offline edits to `/varied/iosxe_config.txt` were useful as a recovery step, but they were not a full substitute on a pristine raw image.

## Inputs

Download the tested image from Cisco:

- [Catalyst 9800-CL Wireless Controller for Cloud, IOSXE-17.15.4d](https://software.cisco.com/download/home/286322605/type/282046477/release/IOSXE-17.15.4d)

Use:

- Cisco login: required
- artifact: `C9800-CL-universalk9.17.15.04d.qcow2`
- helper VM inside GCP: strongly recommended

## Do Not Start From Marketplace

The current Marketplace entries visible for `C9800-CL` are old:

- `16.12.1`
- `16.12.2s`
- `17.2.1`
- `17.3.5a`

Those are roughly 2019 to 2021 era trains. This lab used `17.15.04d`.

Cisco's public GCP-facing material still appears to steer users toward Marketplace, but it is not a good baseline if the goal is a current controller.

## Build The Controller

### 1. Prepare on a helper VM

Use a small helper VM in GCP to:

- mount the Cisco `qcow2`
- edit boot files offline
- seed or inspect files under `/varied`
- move patched artifacts into Cloud Storage before import

### 2. Patch the image for GCP bootstrap

The stock raw image did not come up as a healthy GCP controller on its own.

This mattered because the GCP bootstrap path appears to build Cisco-owned first-boot state, not just apply a little metadata. Skipping it entirely left the raw image without enough state to become a healthy controller, even when `/varied/iosxe_config.txt` was created offline by hand.

The changes that mattered were:

- add `CSR_GCP` and `EWLC_GCP` to the kernel command line in `grub2/grub.cfg`
- seed `/varied/gcp-ovf-env.xml`
- replace Cisco's crashing `decode-custom-data.py`

Shim used in this repo:

- [examples/image-patching/decode-custom-data-minimal.py](examples/image-patching/decode-custom-data-minimal.py)

### 3. Stop after the first boot that reaches Cisco's GCP path

Do not keep rebooting once you have a boot that clearly enters Cisco's GCP bootstrap path. Preserve that disk and inspect it offline first.

Treat the boot as "good enough to preserve" when serial or logs show signs like:

- `GCP BOOT: Autonomous Mode`
- `parse_metadata_json.py ... gcp_customdata`
- `/bootflash/gcp/gcp_boot.log` exists on disk
- `/varied/CustomData.bak` exists on disk

Before changing anything else, inspect:

- `/bootflash/gcp/gcp_boot.log`
- `/varied/CustomData.bak`
- `/varied/iosxe_config.txt`

### 4. Append the final Day 0 CLI into `/varied/iosxe_config.txt`

This was the change that made the controller usable.

Examples:

- [examples/day0/iosxe_config.append.cli](examples/day0/iosxe_config.append.cli)
- [examples/day0/gcp-customdata.txt](examples/day0/gcp-customdata.txt)

Important items in that file:

- local admin user
- local login on console and VTY
- `ip http server`
- `ip http secure-server`
- `wireless management interface GigabitEthernet1`

### 5. Set management IP manually if needed

In the working lab, `GigabitEthernet1` came up without an address from DHCP.

Example:

```cli
interface GigabitEthernet1
 ip address 10.10.0.33 255.255.255.0
 no shutdown
ip route 0.0.0.0 0.0.0.0 10.10.0.1
write memory
```

### 6. Set the wireless country code

This cleared the last WebUI setup blocker:

```cli
wireless country US
write memory
```

## Acceptance Checks

From the controller:

```cli
show version
show ip interface brief | include GigabitEthernet1
show running-config | include wireless management interface
show running-config | include ^ip http
show running-config | include ^wireless country
```

Expected:

- expected release is running
- `GigabitEthernet1` is not `unassigned`
- both HTTP commands exist
- country code exists

From outside the VM:

```bash
ssh <admin-user>@<controller-public-ip>
curl -k -I https://<controller-public-ip>/webui/
```

Expected:

- SSH login works
- HTTPS responds instead of timing out
- WebUI lands in the normal dashboard

## AP Join

### 1. Fix DTLS first if join fails early

Controller-side command that mattered:

```cli
wireless config vwlc-ssc key-size 2048 signature-algo sha256 password 0 <ssc-password>
```

### 2. Make the controller usable for public-cloud AP discovery

Needed on the controller:

- `wireless management interface GigabitEthernet1`
- controller public IP configured where your release expects it
- on the remote-site AP profile:
  - `no capwap-discovery private`
  - `capwap-discovery public`

### 3. Use AP serial when needed

Lab notes that worked:

- macOS adapter path: `/dev/cu.usbserial-*`
- serial settings: `9600 8N1`
- default post-reset login: `Cisco / Cisco`

Quick macOS flow:

```bash
ls /dev/cu.usbserial*
screen /dev/cu.usbserial-XXXX 9600
```

Useful AP-side commands:

```cli
show version
show capwap ip config
show capwap client rcb
capwap ap primary-base WLC1 <controller-public-ip>
```

If default AP serial login stops working after join, push an AP management user from the controller:

```cli
mgmtuser username <user> password 0 <password> secret 0 <password>
```

### 4. Use `FlexConnect`

`Local` mode looked promising at first but was not the correct operational mode on this public-cloud WLC. `FlexConnect` with local switching was the working path.

Examples:

- [examples/wlan/flexconnect-open-policy.cli](examples/wlan/flexconnect-open-policy.cli)
- [examples/wlan/remote-site-tag.cli](examples/wlan/remote-site-tag.cli)

### 5. Verify the AP is really healthy

Run:

```cli
show ap summary
show wireless stats ap join summary
show ap name <ap-name> config general
```

Expected:

- AP is registered
- join state is `Joined`
- `AP Mode : FlexConnect`
- clients actually work on the SSID

## Appendix: Known Dead Ends

- booting the stock raw `qcow2` and hoping Cisco's GCP bootstrap would sort itself out
- using Marketplace as the deployment baseline
- creating `/varied/iosxe_config.txt` on a pristine imported disk and expecting that alone to produce a healthy WLC

That last shortcut was only partially useful. It seeded hostname and login on AUX, but it still did not produce working SSH, HTTPS, or a usable IOS console on the pristine raw image.

## Repo Files

- [examples/day0/iosxe_config.append.cli](examples/day0/iosxe_config.append.cli)
- [examples/day0/gcp-customdata.txt](examples/day0/gcp-customdata.txt)
- [examples/image-patching/decode-custom-data-minimal.py](examples/image-patching/decode-custom-data-minimal.py)
- [examples/wlan/flexconnect-open-policy.cli](examples/wlan/flexconnect-open-policy.cli)
- [examples/wlan/remote-site-tag.cli](examples/wlan/remote-site-tag.cli)
