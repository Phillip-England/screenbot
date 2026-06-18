package screenbot

import (
	"fmt"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"math"
	"os"
	"sort"
	"time"
)

type TemplateMatch struct {
	Box          Box     `json:"box"`
	Confidence   float64 `json:"confidence"`
	TemplatePath string  `json:"template_path"`
}

func (m TemplateMatch) Center() Point { return m.Box.Center() }

type MatchOptions struct {
	Confidence     float64
	SearchBox      *Box
	Grayscale      bool
	DedupeDistance int
	Limit          int
}

func defaultMatchOptions(options MatchOptions) MatchOptions {
	if options.Confidence == 0 {
		options.Confidence = .85
	}
	if options.DedupeDistance == 0 {
		options.DedupeDistance = 10
	}
	return options
}

func matchScreenshot(searchBox *Box) (*image.RGBA, Point, error) {
	if searchBox == nil {
		img, err := Screenshot(nil)
		return img, Point{}, err
	}
	box, err := searchBox.ClampToScreen()
	if err != nil {
		return nil, Point{}, err
	}
	img, err := Screenshot(&box)
	return img, Point{box.Left, box.Top}, err
}

func readImage(path string) (image.Image, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	img, _, err := image.Decode(f)
	if err != nil {
		return nil, fmt.Errorf("read template %q: %w", path, err)
	}
	return img, nil
}

func imageValues(img image.Image, grayscale bool) ([]float64, int, int) {
	w, h := img.Bounds().Dx(), img.Bounds().Dy()
	channels := 3
	if grayscale {
		channels = 1
	}
	values := make([]float64, w*h*channels)
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			c := rgbAt(img, x, y)
			i := (y*w + x) * channels
			if grayscale {
				values[i] = .299*float64(c.R) + .587*float64(c.G) + .114*float64(c.B)
			} else {
				values[i], values[i+1], values[i+2] = float64(c.R), float64(c.G), float64(c.B)
			}
		}
	}
	return values, w, h
}

func matchImage(haystack, needle image.Image, grayscale bool) ([]scoredPoint, error) {
	hv, hw, hh := imageValues(haystack, grayscale)
	nv, nw, nh := imageValues(needle, grayscale)
	channels := 3
	if grayscale {
		channels = 1
	}
	if hw < nw || hh < nh {
		return nil, fmt.Errorf("template image is larger than screenshot/search region")
	}
	n := float64(len(nv))
	var needleSum, needleSq float64
	for _, v := range nv {
		needleSum += v
		needleSq += v * v
	}
	needleVariance := needleSq - needleSum*needleSum/n
	result := make([]scoredPoint, 0, (hw-nw+1)*(hh-nh+1))
	for y := 0; y <= hh-nh; y++ {
		for x := 0; x <= hw-nw; x++ {
			var sum, sq, cross float64
			for ty := 0; ty < nh; ty++ {
				hi := ((y+ty)*hw + x) * channels
				ni := ty * nw * channels
				for i := 0; i < nw*channels; i++ {
					v := hv[hi+i]
					sum += v
					sq += v * v
					cross += v * nv[ni+i]
				}
			}
			hayVariance := sq - sum*sum/n
			denominator := math.Sqrt(max(0, hayVariance) * max(0, needleVariance))
			score := 0.0
			if denominator > 0 {
				score = (cross - sum*needleSum/n) / denominator
			} else if hayVariance == 0 && needleVariance == 0 && math.Abs(sum-needleSum) < .5 {
				score = 1
			}
			result = append(result, scoredPoint{score, x, y})
		}
	}
	return result, nil
}

type scoredPoint struct {
	score float64
	x, y  int
}

func LocateImage(path string, options MatchOptions) (*TemplateMatch, error) {
	options = defaultMatchOptions(options)
	screen, offset, err := matchScreenshot(options.SearchBox)
	if err != nil {
		return nil, err
	}
	template, err := readImage(path)
	if err != nil {
		return nil, err
	}
	scores, err := matchImage(screen, template, options.Grayscale)
	if err != nil {
		return nil, err
	}
	if len(scores) == 0 {
		return nil, nil
	}
	best := scores[0]
	for _, candidate := range scores[1:] {
		if candidate.score > best.score {
			best = candidate
		}
	}
	if best.score < options.Confidence {
		return nil, nil
	}
	match := &TemplateMatch{Box: BoxFromXYWH(offset.X+best.x, offset.Y+best.y, template.Bounds().Dx(), template.Bounds().Dy()), Confidence: best.score, TemplatePath: path}
	return match, nil
}

func LocateAllImages(path string, options MatchOptions) ([]TemplateMatch, error) {
	options = defaultMatchOptions(options)
	screen, offset, err := matchScreenshot(options.SearchBox)
	if err != nil {
		return nil, err
	}
	template, err := readImage(path)
	if err != nil {
		return nil, err
	}
	scores, err := matchImage(screen, template, options.Grayscale)
	if err != nil {
		return nil, err
	}
	sort.Slice(scores, func(i, j int) bool { return scores[i].score > scores[j].score })
	matches := make([]TemplateMatch, 0)
	for _, candidate := range scores {
		if candidate.score < options.Confidence {
			break
		}
		box := BoxFromXYWH(offset.X+candidate.x, offset.Y+candidate.y, template.Bounds().Dx(), template.Bounds().Dy())
		center := box.Center()
		duplicate := false
		for _, existing := range matches {
			if center.DistanceTo(existing.Center()) <= float64(options.DedupeDistance) {
				duplicate = true
				break
			}
		}
		if duplicate {
			continue
		}
		matches = append(matches, TemplateMatch{box, candidate.score, path})
		if options.Limit > 0 && len(matches) >= options.Limit {
			break
		}
	}
	return matches, nil
}

func WaitForImage(path string, timeout, pollInterval time.Duration, options MatchOptions) (TemplateMatch, error) {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		match, err := LocateImage(path, options)
		if err != nil {
			return TemplateMatch{}, err
		}
		if match != nil {
			return *match, nil
		}
		time.Sleep(pollInterval)
	}
	return TemplateMatch{}, fmt.Errorf("image not found within %s: %s", timeout, path)
}

func MoveToImage(path string, options MatchOptions, move MoveOptions) (Point, error) {
	match, err := LocateImage(path, options)
	if err != nil {
		return Point{}, err
	}
	if match == nil {
		return Point{}, fmt.Errorf("image not found: %s", path)
	}
	return MoveTo(match.Center(), move)
}
func ClickImage(path string, options MatchOptions, click ClickOptions) (Point, error) {
	match, err := LocateImage(path, options)
	if err != nil {
		return Point{}, err
	}
	if match == nil {
		return Point{}, fmt.Errorf("image not found: %s", path)
	}
	return Click(match.Center(), click)
}

func ClickImageWhenVisible(path string, timeout, pollInterval time.Duration, options MatchOptions, click ClickOptions) (Point, error) {
	match, err := WaitForImage(path, timeout, pollInterval, options)
	if err != nil {
		return Point{}, err
	}
	return Click(match.Center(), click)
}
