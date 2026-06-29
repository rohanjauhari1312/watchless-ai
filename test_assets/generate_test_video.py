"""Generates a self-contained synthetic test clip with deterministic on-screen
text so the vision pipeline can be validated end-to-end without a real camera.

Three zones, three storylines, all running in parallel so duration/identity
queries can be tested against the same clip:
  - Driveway (top):      red sedan parked 20-90s, then a blue pickup 100-140s
  - Water bowl (bottom-left):  dog drinking water 40-60s
  - Study desk (bottom-right): child studying continuously 10-130s
"""
import cv2
import numpy as np

WIDTH, HEIGHT = 900, 600
FPS = 10
DURATION_SECONDS = 150
OUT_PATH = "test_assets/sample_clip.mp4"

DRIVEWAY_BOX = (40, 40, 860, 260)
BOWL_BOX = (40, 300, 430, 560)
DESK_BOX = (470, 300, 860, 560)


def draw_zone(frame, box, label):
    x1, y1, x2, y2 = box
    cv2.rectangle(frame, (x1, y1), (x2, y2), (70, 70, 70), 1)
    cv2.putText(frame, label, (x1 + 8, y1 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (140, 140, 140), 1)


def draw_text_block(frame, box, lines, color):
    x1, y1, x2, y2 = box
    cy = y1 + 60
    for line in lines:
        cv2.putText(frame, line, (x1 + 20, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cy += 30


def render_frame(t: float) -> np.ndarray:
    frame = np.full((HEIGHT, WIDTH, 3), 18, dtype=np.uint8)
    draw_zone(frame, DRIVEWAY_BOX, "DRIVEWAY")
    draw_zone(frame, BOWL_BOX, "WATER BOWL AREA")
    draw_zone(frame, DESK_BOX, "STUDY DESK")

    if 20 <= t < 90:
        draw_text_block(frame, DRIVEWAY_BOX, ["RED SEDAN", "parked in driveway"], (60, 60, 220))
    elif 100 <= t < 140:
        draw_text_block(frame, DRIVEWAY_BOX, ["BLUE PICKUP TRUCK", "parked in driveway"], (220, 130, 40))
    else:
        draw_text_block(frame, DRIVEWAY_BOX, ["driveway empty"], (90, 90, 90))

    if 40 <= t < 60:
        draw_text_block(frame, BOWL_BOX, ["BROWN DOG", "drinking from water bowl"], (60, 180, 220))
    else:
        draw_text_block(frame, BOWL_BOX, ["no animal present"], (90, 90, 90))

    if 10 <= t < 130:
        draw_text_block(frame, DESK_BOX, ["CHILD", "sitting at desk", "studying with books open"], (80, 220, 120))
    else:
        draw_text_block(frame, DESK_BOX, ["desk empty"], (90, 90, 90))

    cv2.putText(frame, f"t={t:0.0f}s", (WIDTH - 110, HEIGHT - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (120, 120, 120), 1)
    return frame


def main():
    writer = cv2.VideoWriter(OUT_PATH, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    total_frames = DURATION_SECONDS * FPS
    for i in range(total_frames):
        t = i / FPS
        writer.write(render_frame(t))
    writer.release()
    print(f"Wrote {OUT_PATH} ({DURATION_SECONDS}s @ {FPS}fps)")


if __name__ == "__main__":
    main()
