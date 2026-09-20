# Spare

**Saves Lives. Saves Us.**

Spare turns video of a real space into an interactive 3D model, helping people understand their surroundings and explore how to move through them.

**[Try Spare at sparesave.us](https://sparesave.us/)** · [Alternate live link](https://smuashdinkytind.vercel.app/)

Open the website to get started—no local installation needed.

## Why Spare

When someone enters an unfamiliar building, the people supporting them may only see fragments: a camera feed, a verbal description, or a few photos. It can be difficult to understand where objects are and how one part of the space connects to another.

Spare brings those views into a shared picture. Our vision is to help responders and the teams supporting them understand a space, discuss obstacles, and plan their next move with more context. A recording becomes something they can explore, revisit, and work with together.

Built for **VTHacks 14**, Spare combines camera capture, AI-assisted reconstruction, and route planning in one browser workspace.

## What it does

- **Capture your surroundings.** Upload a room video or record with a computer webcam. Our glasses camera integration also supports wearable capture and tap-to-record controls with connected hardware.
- **Turn video into a 3D space.** Spare uses real video frames to generate an approximate model of the room and its furnishings.
- **Explore and edit.** Open the Sandbox to rotate and zoom, inspect objects, move furniture, adjust scale, and undo changes.
- **Find a path.** Choose a start and destination to calculate a route around modeled obstacles on a single floor.
- **Keep your work.** Reopen saved scans or export and import scenes to continue working with them.

## Try it

1. Open [Spare](https://sparesave.us/) and upload a room video or record with your webcam.
2. Select **Reconstruct video** and wait for processing to finish.
3. Choose **Enter Sandbox** to explore the result.
4. Open **Agent & Pathfinder**, choose your start and destination, and select **Find path**.

For a clearer reconstruction, record slowly, keep the room well lit, and capture overlapping views from different positions. Glasses capture is optional and requires the camera hardware and companion script.

## A prototype with a purpose

Spare works with real video, but its models and routes are estimates. Unseen areas, dimensions, and door access may be incomplete or incorrect; a suggested path is not a verified safe or emergency exit route. Natural-language agent commands are not connected yet.

## Built with

React, TypeScript, Three.js, FastAPI, Gemini, Blender, and computer vision tools, with Arduino controls for the glasses setup. The Blender video workflow sends selected frames to Gemini to help generate the scene.

For local development and reconstruction setup, see the [Blender integration guide](docs/blender-integration.md). The application lives in `frontend/` and `backend/`.
