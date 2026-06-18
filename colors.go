package screenbot

import (
	"fmt"
	"image"
	"math"
	"time"
)

type ColorMode string

const (
	ChannelMode   ColorMode = "channel"
	EuclideanMode ColorMode = "euclidean"
)

type ColorStats struct {
	Color     RGB `json:"color"`
	Tolerance int `json:"tolerance"`
	Count     int `json:"count"`
	Total     int `json:"total"`
}

func (s ColorStats) Ratio() float64 {
	if s.Total == 0 {
		return 0
	}
	return float64(s.Count) / float64(s.Total)
}
func (s ColorStats) Percent() float64 { return s.Ratio() * 100 }

func colorMatches(got, target RGB, tolerance int, mode ColorMode) (bool, error) {
	dr, dg, db := int(got.R)-int(target.R), int(got.G)-int(target.G), int(got.B)-int(target.B)
	if mode == "" || mode == ChannelMode {
		return abs(dr) <= tolerance && abs(dg) <= tolerance && abs(db) <= tolerance, nil
	}
	if mode == EuclideanMode {
		return math.Sqrt(float64(dr*dr+dg*dg+db*db)) <= float64(tolerance), nil
	}
	return false, fmt.Errorf("unknown color mode %q", mode)
}

func ScanColor(img image.Image, target RGB, tolerance int, mode ColorMode) (ColorStats, error) {
	if tolerance < 0 {
		return ColorStats{}, fmt.Errorf("tolerance cannot be negative")
	}
	stats := ColorStats{Color: target, Tolerance: tolerance, Total: img.Bounds().Dx() * img.Bounds().Dy()}
	for y := 0; y < img.Bounds().Dy(); y++ {
		for x := 0; x < img.Bounds().Dx(); x++ {
			match, err := colorMatches(rgbAt(img, x, y), target, tolerance, mode)
			if err != nil {
				return ColorStats{}, err
			}
			if match {
				stats.Count++
			}
		}
	}
	return stats, nil
}

func GetColorStats(box Box, target RGB, tolerance int, mode ColorMode) (ColorStats, error) {
	img, err := Screenshot(&box)
	if err != nil {
		return ColorStats{}, err
	}
	return ScanColor(img, target, tolerance, mode)
}

func CountColorPixels(box Box, target RGB, tolerance int, mode ColorMode) (int, error) {
	stats, err := GetColorStats(box, target, tolerance, mode)
	return stats.Count, err
}
func ColorPercent(box Box, target RGB, tolerance int, mode ColorMode) (float64, error) {
	stats, err := GetColorStats(box, target, tolerance, mode)
	return stats.Percent(), err
}
func BoxHasColorCount(box Box, target RGB, minCount, tolerance int, mode ColorMode) (bool, error) {
	count, err := CountColorPixels(box, target, tolerance, mode)
	return count >= minCount, err
}
func BoxHasColorPercent(box Box, target RGB, minPercent float64, tolerance int, mode ColorMode) (bool, error) {
	percent, err := ColorPercent(box, target, tolerance, mode)
	return percent >= minPercent, err
}

func validateColorWait(timeout, pollInterval time.Duration) error {
	if timeout < 0 {
		return fmt.Errorf("timeout cannot be negative")
	}
	if pollInterval <= 0 {
		return fmt.Errorf("poll interval must be positive")
	}
	return nil
}

// WaitForColor waits until at least one pixel in box matches target.
func WaitForColor(box Box, target RGB, tolerance int, mode ColorMode, timeout, pollInterval time.Duration) (ColorStats, error) {
	return WaitForColorCount(box, target, 1, tolerance, mode, timeout, pollInterval)
}

// WaitForColorCount waits until at least minCount pixels in box match target.
func WaitForColorCount(box Box, target RGB, minCount, tolerance int, mode ColorMode, timeout, pollInterval time.Duration) (ColorStats, error) {
	if minCount < 1 {
		return ColorStats{}, fmt.Errorf("minimum color count must be positive")
	}
	if err := validateColorWait(timeout, pollInterval); err != nil {
		return ColorStats{}, err
	}
	deadline := time.Now().Add(timeout)
	for {
		stats, err := GetColorStats(box, target, tolerance, mode)
		if err != nil {
			return ColorStats{}, err
		}
		if stats.Count >= minCount {
			return stats, nil
		}
		remaining := time.Until(deadline)
		if remaining <= 0 {
			break
		}
		time.Sleep(min(pollInterval, remaining))
	}
	return ColorStats{}, fmt.Errorf("color %s did not reach %d pixels within %s", target.Hex(), minCount, timeout)
}

// WaitForColorPercent waits until target covers at least minPercent of box.
func WaitForColorPercent(box Box, target RGB, minPercent float64, tolerance int, mode ColorMode, timeout, pollInterval time.Duration) (ColorStats, error) {
	if minPercent <= 0 || minPercent > 100 {
		return ColorStats{}, fmt.Errorf("minimum color percent must be greater than 0 and at most 100")
	}
	if err := validateColorWait(timeout, pollInterval); err != nil {
		return ColorStats{}, err
	}
	deadline := time.Now().Add(timeout)
	for {
		stats, err := GetColorStats(box, target, tolerance, mode)
		if err != nil {
			return ColorStats{}, err
		}
		if stats.Percent() >= minPercent {
			return stats, nil
		}
		remaining := time.Until(deadline)
		if remaining <= 0 {
			break
		}
		time.Sleep(min(pollInterval, remaining))
	}
	return ColorStats{}, fmt.Errorf("color %s did not reach %.2f%% within %s", target.Hex(), minPercent, timeout)
}

func FindNearestColor(anchor Point, target RGB, radius, tolerance int, mode ColorMode, searchBox *Box) (*Point, error) {
	area := BoxAround(anchor, radius)
	if searchBox != nil {
		area = intersectBoxes(area, *searchBox)
	}
	clamped, err := area.ClampToScreen()
	if err != nil {
		return nil, err
	}
	if clamped.Width() <= 0 || clamped.Height() <= 0 {
		return nil, nil
	}
	img, err := Screenshot(&clamped)
	if err != nil {
		return nil, err
	}
	bestDistance := math.MaxInt
	var best *Point
	for y := 0; y < img.Bounds().Dy(); y++ {
		for x := 0; x < img.Bounds().Dx(); x++ {
			match, err := colorMatches(rgbAt(img, x, y), target, tolerance, mode)
			if err != nil {
				return nil, err
			}
			if !match {
				continue
			}
			p := Point{clamped.Left + x, clamped.Top + y}
			dx, dy := p.X-anchor.X, p.Y-anchor.Y
			d := dx*dx + dy*dy
			if d <= radius*radius && d < bestDistance {
				candidate := p
				best = &candidate
				bestDistance = d
			}
		}
	}
	return best, nil
}

// WaitForNearestColor waits for a matching pixel near anchor and returns its screen coordinate.
func WaitForNearestColor(anchor Point, target RGB, radius, tolerance int, mode ColorMode, searchBox *Box, timeout, pollInterval time.Duration) (Point, error) {
	if radius < 0 {
		return Point{}, fmt.Errorf("radius cannot be negative")
	}
	if err := validateColorWait(timeout, pollInterval); err != nil {
		return Point{}, err
	}
	deadline := time.Now().Add(timeout)
	for {
		point, err := FindNearestColor(anchor, target, radius, tolerance, mode, searchBox)
		if err != nil {
			return Point{}, err
		}
		if point != nil {
			return *point, nil
		}
		remaining := time.Until(deadline)
		if remaining <= 0 {
			break
		}
		time.Sleep(min(pollInterval, remaining))
	}
	return Point{}, fmt.Errorf("color %s not found within radius %d and timeout %s", target.Hex(), radius, timeout)
}

func ClickNearestColor(anchor Point, target RGB, radius, tolerance int, mode ColorMode, options ClickOptions) (Point, error) {
	p, err := FindNearestColor(anchor, target, radius, tolerance, mode, nil)
	if err != nil {
		return Point{}, err
	}
	if p == nil {
		return Point{}, fmt.Errorf("color %v not found within radius %d", target, radius)
	}
	return Click(*p, options)
}

// ClickColorWhenVisible waits for the nearest matching pixel and clicks it.
func ClickColorWhenVisible(anchor Point, target RGB, radius, tolerance int, mode ColorMode, searchBox *Box, timeout, pollInterval time.Duration, options ClickOptions) (Point, error) {
	point, err := WaitForNearestColor(anchor, target, radius, tolerance, mode, searchBox, timeout, pollInterval)
	if err != nil {
		return Point{}, err
	}
	return Click(point, options)
}
