#The Toyota BEAN Protocal

# The Toyota BEAN Protocal

## What is the BEAN Protocol?

The **Toyota BEAN (Body Electronics Area Network)** protocol is a proprietary automotive multiplex communication network developed by Toyota. Introduced around 1997 (debuting in vehicles like the Toyota Celsior/Lexus LS), it was specifically designed to network a vehicle's body control systems rather than the engine or chassis.

### 1. Purpose and Application

- **Body Electronics Control:** BEAN was designed for lower-priority, slower-response body functions such as power windows, door locks, climate control (HVAC), interior lighting, and dashboard gauges.
- **Wiring Reduction:** Prior to multiplexing, every switch and actuator required dedicated point-to-point wiring. BEAN allowed multiple electronic control units (ECUs) to communicate over a shared network. This significantly reduced the size, weight, complexity, and cost of the vehicle's wiring harness.

### 2. Technical Specifications

- **Speed:** It operates at a low speed of up to 10 kbps (kilobits per second). While much slower than modern network speeds, it was perfectly adequate for human-operated body electronics where millisecond latency isn't noticeable.
- **Physical Layer:** Unlike high-speed networks that use twisted-pair wiring for noise immunity, BEAN typically uses a single-wire, ground-referenced system. This further reduced wiring weight and manufacturing costs.
- **Access Method:** BEAN utilizes **CSMA/CD** (Carrier Sense Multiple Access with Collision Detection). The ECUs monitor the line to see if it is vacant before sending data. If two ECUs broadcast at the exact same time, the protocol detects the collision and prioritizes the transmission. This method requires very little processing power, making it suitable for inexpensive 8-bit or 16-bit microcontrollers.
- **Data Length:** It supports variable data lengths (typically 1 to 11 bytes), allowing it to easily transmit a wide variety of sensor values, actuator commands, and diagnostic data.

### 3. Integration within the Vehicle

In Toyota and Lexus vehicles from the late 90s through the 2000s, BEAN did not operate alone. Vehicles typically used a multi-network architecture:

- **CAN (Controller Area Network):** Used for high-speed, critical powertrain and braking data (typically 250 to 500 kbps). Note that vehicles in the late 90s and early 2000s did not include CAN.
- **AVC-LAN (Audio Visual Communication-LAN):** Used for the radio, navigation, and infotainment displays.
- **Gateway ECU:** Because these protocols could not natively talk to each other, a Gateway ECU acted as a router. For example, if the air conditioning ECU (on the BEAN network) needed to know the engine coolant temperature (from the CAN network), the Gateway ECU would translate and pass that data across the two networks.

## What does a BEAN message look like?

At the physical and data-link layers, BEAN uses a single-wire bus where the voltage level indicates the bit state. The bus utilizes a **dominant and recessive** signaling method for arbitration, allowing the CSMA/CD (Carrier Sense Multiple Access with Collision Detection) mechanism to resolve collisions without data loss.

A standard BEAN message frame consists of the following sequential fields:

1. **SOF (Start of Frame):** A dominant bit/pulse that wakes up the receiving nodes and synchronizes their timing to indicate a new message is beginning.
2. **PRI (Priority):** A 4-bit field that determines the message's priority. Lower values typically represent higher priority. If two ECUs transmit simultaneously, the one sending a dominant bit while the other sends a recessive bit wins arbitration and continues transmitting.
3. **ML (Message Length):** A 4-bit field indicating the number of data bytes in the payload.
4. **DEST ID (Destination ID):** An 8-bit field specifying the receiving ECU's address. It can target a specific node or act as a broadcast address.
5. **SRC ID (Source ID):** An 8-bit field containing the address of the transmitting ECU.
6. **DATA (Payload):** Between 1 and 11 bytes of actual information. This contains the commands (e.g., "roll down window") or status reports (e.g., "driver door is open").
7. **CRC (Cyclic Redundancy Check):** An 8-bit checksum used by receivers to verify that the message wasn't corrupted by electrical noise during transmission.
8. **EOD (End of Data):** A delimiter indicating the end of the payload and CRC.
9. **ACK (Acknowledge):** A time slot where the targeted receiving ECU(s) pull the bus to the dominant state to confirm successful reception of the frame. If the sender does not see an ACK, it will typically retry the transmission (often up to 3 times).
10. **EOF (End of Frame):** A sequence of recessive bits marking the absolute end of the message transmission, returning the bus to an idle state.

### Electrical & Signal Characteristics

From an electrical and low-level signal perspective:

- **Voltage Levels:** The bus typically operates at vehicle battery voltage (12V) or at 5V. The network idles in a recessive state and is actively pulled to a dominant state by an ECU's transceiver. [**Note:** My 2000 Toyota Crown (JZS173) transmits at 5V everywhere that I have seen it.]
- **Bit Encoding:** BEAN relies on time-based bit pulses. Logic `1`s and `0`s are encoded using pulse-width variations (VPW) or NRZ (Non-Return-to-Zero), depending on the specific implementation generation.
- **Timing:** Operating at a maximum speed of 10 kbps, the minimum bit duration is roughly 100 microseconds. This slow transmission rate makes the protocol highly resilient to the electromagnetic interference (EMI) commonly found in automotive environments, completely eliminating the need for shielded or twisted-pair wiring.
- **Bit stuffing:** BEAN employs a technique used in digital communications called "bit stuffing" where extra, non-information bits are systematically inserted into a data stream. Please see "A Note on Bit Stuffing" below for more information.

### A Simple Example

**Special Note: All timings from this example come from my 2000 Toyota Crown. Timings may vary in your car.**

---

### A Note on Bit Stuffing

In asynchronous serial protocols (like CAN bus, USB, and some implementations of the Toyota BEAN protocol), devices do not share a separate clock wire. Instead, the receiving device relies on the transition from 1 to 0 (or 0 to 1) in the data stream to keep its internal clock synchronized with the sender.

If the data payload naturally contains a long sequence of identical bits (e.g., fifty 1s in a row), the signal voltage won't change for a long time. Without those voltage transitions, the receiver's clock might drift, causing it to lose count of how many bits were actually sent and corrupting the message.

### How it works

To prevent this, the protocol enforces a "stuffing" rule. For example, the CAN bus protocol uses a 5-bit stuffing rule:

**The Sender:** Monitors the data it is transmitting. If it sends 5 bits of the same logic level consecutively (e.g., 11111), it automatically inserts ("stuffs") one bit of the opposite logic level (0) into the stream.

**The Receiver:** Also monitors the incoming data. If it reads 5 identical bits in a row, it expects the next bit to be the opposite level. It reads this stuffed bit to resynchronize its clock, but then immediately discards (de-stuffs) it so the bit doesn't end up in the final parsed payload.

Another reason for bit stuffing is to create unique control sequences. If the protocol defines the End of Frame (EOF) sequence as six 1s in a row (111111), bit stuffing ensures that this sequence can never accidentally occur inside the regular data payload, preventing the receiver from prematurely ending the message.

### A simple example

Let's say we are sending the following data, and using a 5-bit stuffing rule:

**Original Data:**
`1 1 1 1 1 1 0 0 0 0`

**Transmitted:**
`1 1 1 1 1 [0] 1 0 0 0 0`

(The [0] is the stuffed bit, forcing a transition).

<img width="1280" height="167" alt="image" src="https://github.com/user-attachments/assets/46ea182b-1760-4655-b7d8-270bc3fae1a3" />
