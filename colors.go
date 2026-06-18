package screenbot

import (
	"fmt"
	"image"
	"math"
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
