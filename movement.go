package screenbot

import (
	"fmt"
	"math"
	"math/rand/v2"
	"time"
)

func movePointer(target Point, options MoveOptions) error {
	style := options.Style
	if style == "" {
		if options.Duration > 0 {
			style = LinearMovement
		} else {
			style = InstantMovement
		}
	}
	if options.Duration < 0 {
		return fmt.Errorf("move duration cannot be negative")
	}
	if style == InstantMovement {
		return currentBackend().Move(target, 0)
	}
	if style == LinearMovement {
		return currentBackend().Move(target, options.Duration)
	}
	if style != HumanMovement {
		return fmt.Errorf("unknown move style %q", style)
	}
	if options.Detours < 0 || options.DetourRadius < 0 || options.CurveRadius < 0 || options.OvershootDistance < 0 || options.Steps < 0 {
		return fmt.Errorf("human movement distances, detours, and steps cannot be negative")
	}
	if options.PauseChance < 0 || options.PauseChance > 1 {
		return fmt.Errorf("pause chance must be between 0 and 1")
	}
	if options.PauseMin < 0 || options.PauseMax < 0 || options.PauseMax < options.PauseMin {
		return fmt.Errorf("pause range must be non-negative and ordered")
	}

	backend := currentBackend()
	start, err := backend.MousePosition()
	if err != nil {
		return err
	}
	bounds, err := ScreenBox()
	if err != nil {
		return err
	}
	steps := options.Steps
	if steps == 0 {
		steps = max(12, min(80, int(start.DistanceTo(target)/12)))
	}
	anchors := []Point{start}
	for i := 1; i <= options.Detours; i++ {
		t := float64(i) / float64(options.Detours+1)
		base := interpolatePoint(start, target, t)
		anchors = append(anchors, clampToBox(offsetPerpendicular(base, start, target, randomOffset(options.DetourRadius)), bounds))
	}
	if options.OvershootDistance > 0 && start != target {
		dx, dy := float64(target.X-start.X), float64(target.Y-start.Y)
		length := math.Hypot(dx, dy)
		over := Point{
			X: target.X + int(math.Round(dx/length*float64(options.OvershootDistance))),
			Y: target.Y + int(math.Round(dy/length*float64(options.OvershootDistance))),
		}
		anchors = append(anchors, clampToBox(over, bounds))
	}
	anchors = append(anchors, target)

	path := humanPath(anchors, steps, options.CurveRadius, bounds)
	if len(path) == 0 {
		return backend.Move(target, options.Duration)
	}
	stepDuration := options.Duration / time.Duration(len(path))
	for i, point := range path {
		if i == len(path)-1 {
			point = target
		}
		if err := backend.Move(point, stepDuration); err != nil {
			return err
		}
		if i+1 < len(path) && rand.Float64() < options.PauseChance {
			time.Sleep(randomDuration(options.PauseMin, options.PauseMax))
		}
	}
	return nil
}

func humanPath(anchors []Point, steps, curveRadius int, bounds Box) []Point {
	segments := len(anchors) - 1
	points := make([]Point, 0, steps+segments)
	for segment := 0; segment < segments; segment++ {
		start, end := anchors[segment], anchors[segment+1]
		segmentSteps := max(2, steps/segments)
		mid := interpolatePoint(start, end, 0.5)
		control := offsetPerpendicular(mid, start, end, randomOffset(curveRadius))
		for i := 1; i <= segmentSteps; i++ {
			t := float64(i) / float64(segmentSteps)
			t = t * t * (3 - 2*t)
			oneMinusT := 1 - t
			point := Point{
				X: int(math.Round(oneMinusT*oneMinusT*float64(start.X) + 2*oneMinusT*t*float64(control.X) + t*t*float64(end.X))),
				Y: int(math.Round(oneMinusT*oneMinusT*float64(start.Y) + 2*oneMinusT*t*float64(control.Y) + t*t*float64(end.Y))),
			}
			points = append(points, clampToBox(point, bounds))
		}
	}
	return points
}

func interpolatePoint(start, end Point, t float64) Point {
	return Point{
		X: start.X + int(math.Round(float64(end.X-start.X)*t)),
		Y: start.Y + int(math.Round(float64(end.Y-start.Y)*t)),
	}
}

func offsetPerpendicular(point, start, end Point, distance int) Point {
	dx, dy := float64(end.X-start.X), float64(end.Y-start.Y)
	length := math.Hypot(dx, dy)
	if length == 0 {
		return point
	}
	return Point{
		X: point.X + int(math.Round(-dy/length*float64(distance))),
		Y: point.Y + int(math.Round(dx/length*float64(distance))),
	}
}

func randomOffset(radius int) int {
	if radius <= 0 {
		return 0
	}
	magnitude := radius/2 + rand.IntN(radius-radius/2+1)
	if rand.IntN(2) == 0 {
		return -magnitude
	}
	return magnitude
}

func randomDuration(minimum, maximum time.Duration) time.Duration {
	if maximum <= minimum {
		return minimum
	}
	return minimum + time.Duration(rand.Int64N(int64(maximum-minimum)+1))
}

func clampToBox(point Point, box Box) Point {
	return Point{
		X: min(max(point.X, box.Left), box.Right-1),
		Y: min(max(point.Y, box.Top), box.Bottom-1),
	}
}
