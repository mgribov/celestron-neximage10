# Cam33U Windows Driver Static Analysis Report

**Target**: Celestron NexImage 10 (USB VID:PID `199e:8619`, The Imaging Source)
**Analyzed artifacts**: `NexImage_Windows_Driver_Cam33U_setup_5.3.0.2793.exe`, `iCap2.5_Installer.exe`
**Date**: 2026-03-02
**Purpose**: Extract UVC Extension Unit (XU) control information for Linux implementation

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Installer Classification](#2-installer-classification)
3. [File Inventory](#3-file-inventory)
4. [INF Analysis](#4-inf-analysis)
5. [Pixel Format Support (BA81)](#5-pixel-format-support-ba81)
6. [UVC Control Transfer Architecture](#6-uvc-control-transfer-architecture)
7. [GenICam Property Definitions](#7-genicam-property-definitions)
8. [VCD Property GUIDs](#8-vcd-property-guids)
9. [iCap SDK UVC Classes](#9-icap-sdk-uvc-classes)
10. [XU GUID: Not Found — Methodology to Obtain](#10-xu-guid-not-found--methodology-to-obtain)
11. [Linux Implementation Roadmap](#11-linux-implementation-roadmap)
12. [Appendix: Full Control Name List](#12-appendix-full-control-name-list)

---

## 1. Executive Summary

### What was found

Static analysis of the Cam33U Windows driver installer and iCap capture software produced three categories of actionable information:

- **GenICam control definitions** for the TIS 33U camera family: property names, value ranges, defaults, and conversion formulas for saturation, gamma, white balance, trigger, strobe, and GPIO controls.
- **UVC control transfer format**: the `unitId`/`ctrlId`/`req_code`/`len` structure used by the TIS camera service to send UVC requests, confirming the cameras use standard UVC Extension Unit control transfers.
- **Pixel format handling**: `Cam33UFilter.dll` fully handles BA81 (16-bit Bayer), Y16, Y800, and YUY2, confirming these formats are supported at the hardware level.
- **XU control names**: `XU_DIGITAL_INPUT`, `XU_DIGITAL_OUTPUT_V2`, `XU_GAIN_DB`, and `XU_SCALING_MODE_INFO` appear in error log strings, confirming these are Extension Unit control selectors.
- **C++ class inventory** from `TIS_UDSHL12_x64.dll` revealing the full UVC control class hierarchy for white balance, trigger, strobe, and GPIO.

### What was not found

- **The UVC Extension Unit GUID** is not embedded in any extracted binary. This is architecturally expected: the GUID lives in the camera's USB firmware descriptors and is read at runtime by the host driver.
- **XU control selector numeric IDs** (the `ctrlId` byte values for each XU control) are not present as string constants. They are likely hardcoded as integer literals in compiled code or discovered at runtime via descriptor parsing.
- **IntReg hardware register addresses** for the GenICam properties. The `pValue` references point to register definitions that are camera-model-specific and loaded at runtime from the camera's own GenICam XML (for USB3 Vision cameras).

### What it means for Linux

The NexImage 10 (PID `8619`) is **not covered by the Cam33U kernel driver** — it uses the standard Windows UVC driver (`usbvideo.sys`). The iCap software accesses advanced controls via DirectShow `IKsControl` on the UVC Extension Unit node. To replicate this on Linux:

1. Obtain the XU GUID from the camera's USB descriptors (requires camera connected).
2. Map XU control selector IDs by sniffing USB traffic while iCap adjusts controls.
3. Implement XU controls using `uvcvideo` dynamic controls (`UVCIOC_CTRL_MAP`) or direct `ioctl` calls.

The GenICam control definitions (names, ranges, defaults) from this analysis provide the parameter space. The missing piece is the XU GUID and selector-to-control mapping, both obtainable with the camera connected.

---

## 2. Installer Classification

| Property | Value |
|---|---|
| **File** | `NexImage_Windows_Driver_Cam33U_setup_5.3.0.2793.exe` |
| **PE type** | PE32 executable (GUI), Intel 80386 |
| **Installer framework** | Inno Setup |
| **Identification method** | Presence of `TSetupVersionData`, `TSetupHeader`, `TSetupLanguageDetectionMethod` strings |
| **Extraction tool** | `innoextract` |
| **Driver version** | 5.3.0.2793 (installer), kernel drivers v5.0.1 and v5.1.0 |

The second installer, `iCap2.5_Installer.exe`, packages the iCap capture application and the TIS User Device SDK (`TIS_UDSHL12_x64.dll`). It was extracted separately.

---

## 3. File Inventory

### Cam33U Driver Package

| File | Architecture | Role |
|---|---|---|
| `dss_usbcam_33u_501.sys` | amd64 | Legacy kernel-mode driver (v5.0.1.1607) |
| `dss_usbcam_33u_510.sys` | x64 | Windows 10 kernel-mode driver (v5.1.0.1674) |
| `dss_usbcam_33u.inf` | — | Device install script (both driver variants) |
| `dss_km.cat` | — | Catalog / digital signature |
| `WdfCoinstaller01009.dll` | amd64 | WDF coinstaller |
| `Cam33UFilter.dll` | amd64 | DirectShow video capture filter (pixel format conversion) |
| `cam33u_propertypage.dll` | amd64 | Property page UI (uses GenICam node XML) |
| `Cam33UServicePS.dll` | amd64 | COM proxy/stub for inter-process communication |
| `dutils_img_filter_dll_avx1.dll` | amd64 | Image processing (AVX1 codepath) |
| `dutils_img_filter_dll_avx2.dll` | amd64 | Image processing (AVX2 codepath) |
| `Cam33UService.exe` | amd64 | Main camera service (most information-rich binary) |
| `Cam33UService_SessionProxy.exe` | amd64 | Session proxy for multi-user scenarios |
| `FilterPackage.exe` | amd64 | DirectShow filter registration helper |

### iCap Package

| File | Architecture | Role |
|---|---|---|
| `TIS_UDSHL12_x64.dll` | x64 | TIS User Device SDK (DirectShow wrapper) |
| `iCap.exe` | x64 | iCap capture application |

---

## 4. INF Analysis

### Supported Devices

The `dss_usbcam_33u.inf` defines hardware IDs for the 33U camera series under VID `199E`:

| PID Range | Description |
|---|---|
| `70xx` | Test/development entries |
| `90xx` | Production 33U cameras |
| `9082` | Specific 33U model |
| `9086` | Specific 33U model |
| `94xx` | 33U variant series |
| `98xx` | 33U variant series |
| `9Cxx` | 33U variant series |

### Key Finding: PID 8619 is Absent

**PID `8619` (NexImage 10) does not appear in `dss_usbcam_33u.inf`.**

The Cam33U driver package targets a newer product generation (USB3 Vision / newer UVC cameras). The NexImage 10 is an older-generation UVC 1.10 device that uses the built-in Windows UVC class driver (`usbvideo.sys`) for basic capture. The iCap software provides advanced controls by communicating with the UVC Extension Unit via DirectShow `IKsControl` — it does not depend on the Cam33U kernel driver.

This means the NexImage 10's architecture on Windows mirrors what is achievable on Linux: the standard UVC driver handles capture, and a userspace application sends XU control requests to the Extension Unit.

### Installed GUIDs

| GUID | Meaning |
|---|---|
| `{5dc9399a-8f79-4aea-970b-cc70473849e9}` | `GUID_DSS_KM_DRIVERINTERFACE_USBLEG` (driver interface for 33U devices) |
| `{6bdd1fc6-810f-11d0-bec7-08002be2092f}` | Windows Image device class GUID |

---

## 5. Pixel Format Support (BA81)

`Cam33UFilter.dll` contains comparison chains that explicitly handle the following pixel formats:

| FourCC | Description | Handler |
|---|---|---|
| `BA81` | 16-bit Bayer (primary 16-bit format) | Full handling with demosaic pipeline |
| `RGGB` | 8-bit Bayer (Red-Green-Green-Blue) | Demosaic pipeline |
| `GRBG` | 8-bit Bayer (Green-Red-Blue-Green) | Demosaic pipeline |
| `GBRG` | 8-bit Bayer (Green-Blue-Red-Green) | Demosaic pipeline |
| `BA16` | 16-bit Bayer variant | Handled |
| `Y16` | 16-bit monochrome | Handled |
| `Y800` / `Y8` | 8-bit monochrome | Handled |
| `YUY2` | Packed 4:2:2 YCbCr | Handled |

### Software Post-Processing (Not Hardware XU Controls)

The filter DLL also contains these image processing classes:

- `img_pipe::functions::apply_whitebalance` — software white balance correction
- `img_pipe::functions::apply_saturation_hue_params` — software saturation/hue adjustment

These are **software-side** post-processing functions running in the DirectShow filter graph on the host CPU. They are not hardware Extension Unit controls. This distinction matters: even without XU access, some controls (white balance correction, saturation) can be implemented in software on the Linux side.

### Implication for Linux BA81 Support

The presence of full BA81 handling in the Windows filter confirms that the camera hardware does output 16-bit Bayer data. On Linux, `uvcvideo` rejects BA81 because it does not recognize the format GUID. Two approaches exist:

1. **Patch `uvcvideo`** to add the BA81 format GUID mapping.
2. **Use `tiscamera`** (The Imaging Source open-source driver, Apache 2.0) which natively supports BA81.
3. **Use `libusb`** to bypass `uvcvideo` and handle format negotiation directly.

---

## 6. UVC Control Transfer Architecture

### Transfer Format

The `Cam33UService.exe` binary contains this log format string:

```
({}) [unitId=0x{:x},ctrlId=0x{:2x}] req_code=0x{:2x}, len={:2}
```

This maps directly to UVC class-specific control transfers:

| Field | UVC Equivalent | Description |
|---|---|---|
| `unitId` | `wIndex` high byte | UVC unit ID: Processing Unit (typically `0x02`), Extension Unit (vendor-assigned) |
| `ctrlId` | `wValue` high byte | Control Selector (CS): identifies which control within the unit |
| `req_code` | `bRequest` | UVC request code |
| `len` | `wLength` | Data payload length in bytes |

### UVC Request Codes

| Code | Name | Direction |
|---|---|---|
| `0x01` | `SET_CUR` | Host to device (set current value) |
| `0x81` | `GET_CUR` | Device to host (get current value) |
| `0x82` | `GET_MIN` | Device to host (get minimum value) |
| `0x83` | `GET_MAX` | Device to host (get maximum value) |
| `0x87` | `GET_DEF` | Device to host (get default value) |

### Extension Unit Validation

The service also logs:

```
[Cam33U] Invalid number of VC_EXTENSION_UNIT units for interface 0.
```

This confirms that `Cam33UService.exe` parses the UVC Video Control interface descriptor, enumerates Extension Unit descriptors, and validates them. The service expects specific XU units to be present.

### Named XU Controls

The following Extension Unit control names appear in error log messages within `Cam33UService.exe`:

| XU Control Name | Context |
|---|---|
| `XU_DIGITAL_INPUT` | GPIO digital input control |
| `XU_DIGITAL_OUTPUT_V2` | GPIO digital output control (version 2) |
| `XU_GAIN_DB` | Gain in decibels (hardware-level gain) |
| `XU_SCALING_MODE_INFO` | Image scaling/binning mode |

These names appear in strings like `"Failed to find XU_GAIN_DB property"`, confirming they are XU control identifiers. The numeric selector IDs (the `ctrlId` byte values) for these controls are not present as string constants in the binary.

---

## 7. GenICam Property Definitions

`Cam33UService.exe` embeds GenICam XML fragments defining the property model for the 33U camera family. These definitions follow the GenICam Standard Features Naming Convention (SFNC) with TIS-specific extensions.

### Saturation Control

```xml
<Integer Name="SaturationRaw" NameSpace="Custom">
    <Extension>
        <Default>64</Default>
        <VCDCategoryName>Color</VCDCategoryName>
        <VCDItemName>Saturation</VCDItemName>
        <VCDItemGUID>{284C0E09-010B-45BF-8291-09D90A459B28}</VCDItemGUID>
        <VCDElementName>Value</VCDElementName>
        <VCDElementGUID>{B57D3000-0AC6-4819-A609-272A33140ACA}</VCDElementGUID>
    </Extension>
    <pValue>SaturationRegister</pValue>
    <Min>0</Min>
    <Max>255</Max>
</Integer>
```

| Property | Value |
|---|---|
| Raw range | 0 -- 255 |
| Default (raw) | 64 |
| Conversion | `percent = raw * 100 / 64` |
| Percent range | 0% -- 398.4375% |
| Register | `SaturationRegister` (address loaded at runtime) |

### Gamma Control

```xml
<Integer Name="GammaRaw" NameSpace="Custom">
    <Extension>
        <Default>100</Default>
        <VCDCategoryName>Image</VCDCategoryName>
        <VCDItemName>Gamma</VCDItemName>
        <VCDItemGUID>{284C0E0B-010B-45BF-8291-09D90A459B28}</VCDItemGUID>
        <VCDElementGUID>{B57D3000-0AC6-4819-A609-272A33140ACA}</VCDElementGUID>
    </Extension>
    <pValue>GammaRegister</pValue>
    <Min>1</Min>
    <Max>500</Max>
</Integer>
```

| Property | Value |
|---|---|
| Raw range | 1 -- 500 |
| Default (raw) | 100 |
| Conversion | `gamma_float = raw / 100.0` |
| Float range | 0.01 -- 5.00 |
| Register | `GammaRegister` (address loaded at runtime) |

### Register Address Note

The `pValue` references (`SaturationRegister`, `GammaRegister`, etc.) point to `IntReg` definitions that specify hardware register addresses. These register definitions are camera-model-specific and are loaded at runtime from the camera's GenICam XML description (for USB3 Vision cameras). They were not found as static data in the binary. For UVC cameras like the NexImage 10, the equivalent functionality is accessed through UVC Extension Unit control selectors, not GenICam register addresses.

---

## 8. VCD Property GUIDs

The TIS Video Capture Device (VCD) property system uses GUIDs to identify control items and element types. These GUIDs were found in both `Cam33UService.exe` and `TIS_UDSHL12_x64.dll`.

### Control Item GUIDs

| GUID | VCD Item |
|---|---|
| `{284C0E09-010B-45BF-8291-09D90A459B28}` | Saturation |
| `{284C0E0B-010B-45BF-8291-09D90A459B28}` | Gamma |

The GUID family `{284C0Exx-010B-45BF-8291-09D90A459B28}` appears to encode different VCD items by varying the byte at offset 3 (`0x09` = Saturation, `0x0B` = Gamma). Other values in this family likely map to additional controls (exposure, gain, white balance, etc.).

### Element Type GUIDs

| GUID | VCD Element Type |
|---|---|
| `{B57D3000-0AC6-4819-A609-272A33140ACA}` | Value (generic scalar element) |
| `{99B44940-BFE1-4083-ADA1-BE703F4B8E03}` | Element type family member (range, switch, or similar) |

### Unresolved GUIDs

| GUID | Notes |
|---|---|
| `{21029bdc-0a78-4031-a329-8673e33e0c05}` | Found in TIS VCD property context; purpose not determined |
| `{83229830-3453-41a4-a065-0034022384f0}` | Found in TIS VCD property context; purpose not determined |
| `{EFD4AB61-09E2-444A-9AC1-463434A62B04}` | Found in TIS VCD property context; purpose not determined |

---

## 9. iCap SDK UVC Classes

`TIS_UDSHL12_x64.dll` (the TIS User Device SDK from the iCap installer) contains C++ RTTI strings revealing the UVC control class hierarchy. These classes implement the DirectShow `IKsControl` interface to communicate with UVC Extension Units.

### White Balance

| Class | Role |
|---|---|
| `CUVCWhiteBalanceData` | White balance data transport |
| `CVCDTisWhiteBalanceItem` | Top-level white balance property item |
| `CVCDTisWhiteBalanceAuto` | Auto white balance control |
| `CVCDTisWhiteBalanceOnePush` | One-push (single-shot) white balance |
| `CVCDTisWhiteBalanceRegister` | Hardware register access for white balance |
| `CVCDTisWhiteBalanceSubItemRange` | White balance channel range (R/G/B sub-items) |

### Trigger

| Class | Role |
|---|---|
| `CUVCTrigger` | UVC trigger control transport |
| `CVCDTisTriggerModeItem` | Top-level trigger mode property item |
| `CVCDTisTriggerModeEnableInterface` | Trigger enable/disable interface |

### GPIO

| Class | Role |
|---|---|
| `CUVCGPIO` | UVC GPIO control transport |
| `CVCDTisGPIOItem` | Top-level GPIO property item |
| `CVCDTisGPIOButtonInterface` | GPIO button interface (for external trigger buttons) |

### Strobe

| Class | Role |
|---|---|
| `CUVCStrobe` | UVC strobe control transport |
| `CVCDStrobeItem` | Top-level strobe property item |

### Architectural Significance

The `CUVC*` classes (prefixed with `CUVC`) handle the low-level UVC control transfers to the camera hardware. The `CVCD*` classes (prefixed with `CVCD`) wrap these in the TIS VCD property model exposed to application code. This two-layer design confirms that white balance, trigger, strobe, and GPIO are all **hardware controls** accessed via UVC Extension Unit transfers, not software post-processing.

---

## 10. XU GUID: Not Found -- Methodology to Obtain

### Why the GUID is Not in the Binaries

The UVC Extension Unit GUID is embedded in the camera's **USB firmware**, specifically in the Extension Unit Descriptor within the Video Control Interface Descriptor. This descriptor is part of the USB Configuration Descriptor returned by the standard `GET_DESCRIPTOR` request during device enumeration.

The host-side software does not need to hardcode this GUID. The Windows UVC class driver (`usbvideo.sys`) reads the XU descriptor from the camera, creates a KS (Kernel Streaming) node for it, and exposes the XU GUID through the DirectShow filter topology. The TIS SDK queries this topology at runtime to discover the XU node and send control requests. This is standard UVC architecture and explains why no XU GUID appears in any extracted binary.

### Methods to Obtain the XU GUID

All methods require the NexImage 10 to be physically connected.

**Method 1: Linux USB descriptor dump (recommended)**

```bash
# Requires camera connected to Linux (or WSL2 via usbipd)
lsusb -v -d 199e:8619 | grep -A 30 "Extension Unit"
```

This prints the Extension Unit Descriptor including the GUID, unit ID, and supported control bitmap.

**Method 2: Raw USB descriptor file**

```bash
# Read the raw USB configuration descriptor
xxd /sys/class/video4linux/video0/device/../descriptors | less
# Parse manually: look for bDescriptorSubType = 0x06 (VC_EXTENSION_UNIT)
```

**Method 3: `uvcdynctrl` (if installed)**

```bash
uvcdynctrl -d /dev/video0 -l
```

Lists all UVC controls including Extension Unit controls with their GUIDs.

**Method 4: USB traffic capture on Windows**

Using Wireshark with USBPcap (or USBMon on Linux), capture traffic while iCap adjusts a known XU control (e.g., changing white balance mode). The UVC class-specific control transfer will contain the XU unit ID in `wIndex` and the control selector in `wValue`. The XU GUID can then be correlated from the initial `GET_DESCRIPTOR` response captured at device enumeration.

**Method 5: `uvcvideo` kernel driver debug output**

```bash
# Enable verbose UVC debug logging
echo 0xffff > /sys/module/uvcvideo/parameters/trace
# Plug in camera, then check kernel log
dmesg | grep -i "extension unit"
```

---

## 11. Linux Implementation Roadmap

### Phase 1: Obtain XU Descriptor (requires camera)

1. Connect the NexImage 10 to the Linux host (or attach via `usbipd` on WSL2).
2. Dump the Extension Unit Descriptor:
   ```bash
   lsusb -v -d 199e:8619 2>/dev/null | grep -A 30 "Extension Unit"
   ```
3. Record: the XU GUID, the unit ID (`bUnitID`), and the control bitmap (`bmControls`).
4. The control bitmap indicates how many controls the XU supports and which selector IDs are valid (bit N set means selector N+1 is implemented).

### Phase 2: Map Control Selectors (requires camera + Windows or USB sniffing)

Two approaches:

**Approach A: Probe on Linux**

For each valid selector ID (from the `bmControls` bitmap):

```python
import fcntl
import struct

# UVC XU control query via UVCIOC_CTRL_QUERY
# selector = 1, 2, 3, ... (from bmControls bitmap)
# Send GET_CUR, GET_MIN, GET_MAX, GET_DEF for each
# Record which selectors respond and their data lengths
```

**Approach B: USB traffic capture on Windows**

1. Install USBPcap or Wireshark on Windows.
2. Start capture, then open iCap and adjust each control one at a time.
3. Filter for UVC class-specific requests (`bRequestType = 0x21` for SET, `0xA1` for GET).
4. Map each iCap control action to the corresponding `unitId`/`ctrlId` pair.

### Phase 3: Register Dynamic Controls with `uvcvideo`

Use `UVCIOC_CTRL_MAP` ioctls to register each XU control with the `uvcvideo` driver:

```python
import ctypes
import fcntl

# Define the mapping structure
class uvc_xu_control_mapping(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_uint32),           # V4L2 control ID
        ("name", ctypes.c_char * 32),       # Control name
        ("entity", ctypes.c_uint8 * 16),    # XU GUID (little-endian)
        ("selector", ctypes.c_uint8),        # Control selector
        ("size", ctypes.c_uint8),            # Control data size (bits)
        ("offset", ctypes.c_uint8),          # Bit offset in control data
        ("v4l2_type", ctypes.c_uint32),      # V4L2_CTRL_TYPE_INTEGER, etc.
        ("data_type", ctypes.c_uint32),      # UVC_CTRL_DATA_TYPE_SIGNED, etc.
    ]

# UVCIOC_CTRL_MAP = _IOWR('u', 0x20, uvc_xu_control_mapping)
```

After registration, the controls become accessible through standard V4L2 control ioctls (`VIDIOC_G_CTRL`, `VIDIOC_S_CTRL`) and tools like `v4l2-ctl`.

### Phase 4: Integrate with Camera Module

Add XU control methods to the existing `CameraControls` class in `camera/controls.py`:

| GenICam Name | Expected XU Selector | V4L2 Control Name | Range | Default |
|---|---|---|---|---|
| `Saturation` | TBD | `saturation` | 0 -- 255 | 64 |
| `Gamma` | TBD | `gamma` | 1 -- 500 (raw) | 100 |
| `BalanceWhiteAuto` | TBD | `white_balance_auto` | 0 -- 1 | TBD |
| `BalanceWhiteTemperature` | TBD | `white_balance_temperature` | TBD | TBD |
| `TriggerMode` | TBD | `trigger_mode` | 0 -- 1 | 0 |
| `StrobeEnable` | TBD | `strobe_enable` | 0 -- 1 | 0 |
| `GPOut` | TBD | `gpio_output` | TBD | TBD |

### Phase 5: Software Fallbacks

For controls that are software-side in the Windows filter graph (identified in Section 5), implement equivalent post-processing in Python:

- **Software white balance correction**: Apply per-channel gain in the demosaic pipeline.
- **Software saturation/hue adjustment**: Apply in HSV color space after demosaic.

These can serve as fallbacks if XU hardware controls are not available or as enhancements on top of hardware controls.

### Alternative: `tiscamera` Integration

The Imaging Source maintains the open-source [`tiscamera`](https://github.com/TheImagingSource/tiscamera) driver (Apache 2.0 license). It natively supports TIS cameras including:

- BA81 (16-bit Bayer) format handling
- Extension Unit control access
- GStreamer integration

If direct `uvcvideo` XU mapping proves difficult, `tiscamera` may provide a faster path to full feature support. It should be evaluated during Phase 1 to determine whether it recognizes the NexImage 10 (PID `8619`).

---

## 12. Appendix: Full Control Name List

Complete list of control property names found in the `Cam33UService.exe` string table:

### Exposure and Gain

| Name | Category |
|---|---|
| `ExposureTime` | Exposure |
| `ExposureAuto` | Exposure |
| `ExposureAutoReference` | Exposure |
| `ExposureAutoUpperLimit` | Exposure |
| `ExposureAutoUpperLimitAuto` | Exposure |
| `Gain` | Gain |
| `GainRawHidden` | Gain (internal) |
| `GainAuto` | Gain |

### White Balance

| Name | Category |
|---|---|
| `BalanceWhiteAuto` | White Balance |
| `BalanceWhiteTemperature` | White Balance |
| `BalanceWhiteMode` | White Balance |
| `WhiteBalanceMode_Temperature` | White Balance |
| `WhiteBalanceMode_GrayWorld` | White Balance |
| `VCDProperty_WhiteBalanceGreen` | White Balance |
| `VCDProperty_WhiteBalanceRed` | White Balance |
| `VCDProperty_WhiteBalanceBlue` | White Balance |

### Image Processing

| Name | Category |
|---|---|
| `Saturation` | Color |
| `SaturationRaw` | Color (internal) |
| `Gamma` | Image |
| `GammaRaw` | Image (internal) |

### Trigger

| Name | Category |
|---|---|
| `TriggerMode` | Trigger |
| `TriggerSoftware` | Trigger |
| `TriggerActivation` | Trigger |
| `TriggerDelay` | Trigger |

### Strobe

| Name | Category |
|---|---|
| `StrobeEnable` | Strobe |
| `StrobeOperation` | Strobe |
| `StrobePolarity` | Strobe |
| `StrobeDelay` | Strobe |
| `StrobeDuration` | Strobe |

### GPIO

| Name | Category |
|---|---|
| `GPIn` | GPIO |
| `GPOut` | GPIO |

### Orientation

| Name | Category |
|---|---|
| `ReverseX` | Image |
| `ReverseY` | Image |

### Extension Unit Controls (from error log strings)

| Name | Category |
|---|---|
| `XU_DIGITAL_INPUT` | GPIO (XU) |
| `XU_DIGITAL_OUTPUT_V2` | GPIO (XU) |
| `XU_GAIN_DB` | Gain (XU) |
| `XU_SCALING_MODE_INFO` | Scaling (XU) |

### Supported Sensor Models (from service binary)

| Sensor ID | Notes |
|---|---|
| `MT9V023` | Aptina VGA global shutter |
| `MT9M001` | Aptina 1.3MP |
| `MT9T031` | Aptina 3MP |
| `MT9M131` | Aptina 1.3MP (SoC variant) |
| `MT9D131` | Aptina 2MP (SoC variant) |
| `MT9M021` | Aptina 1.2MP global shutter |
| `MT9P031` | Aptina 5MP (likely NexImage 10 sensor candidate) |
| `AR0234` | ON Semi 2.3MP global shutter |
| `IMX290` | Sony 2.1MP (Starvis, low-light) |

### Debug Registers (33U cameras only)

| Address | Name |
|---|---|
| `0xCEBB000100000020` | `DebugPropertiesImplemented` |
| `0xCEBB000100000028` | `ServiceLogLevel_Reg` (values 0--5) |
| `0xCEBB00010000002C` | `ServiceLogLevel_LogGenICamRequests_Reg` |
| `0xCEBB000100000034` | `ServiceLogLevel_LogUVCRequests_Reg` |

These debug registers are accessible only on 33U-series cameras (not the NexImage 10) and can enable verbose UVC request logging that would reveal XU control selector IDs.
