# Kling AI Nodes Update Plan

## Overview
Kling AI has released significant updates including v2.0 models, new API endpoints, image generation capabilities, multi-image video generation, and video effects. This document outlines the comprehensive update plan for all Kling nodes.

## Key Changes from API Documentation

### API Endpoint Update
- **Old**: `https://api.klingai.com`
- **New**: `https://api-singapore.klingai.com`

### Model Capability Matrix (from API Documentation)

Full API documentation can be accessed at https://app.klingai.com/global/dev/document-api/quickStart/productIntroduction/overview you will also find links to model specific documentations pages later in this plan in the relevant sections.

| Model | Text-to-Video | Image-to-Video | Multi-Image | Video Extension | Lip-Sync | Video Effects | Camera Control | Motion Brush |
|-------|---------------|----------------|-------------|-----------------|----------|---------------|----------------|--------------|
| **kling-v1** | ✅ All modes | ✅ All modes | ❌ | ❌ | ❌ | ✅ All modes | ✅ | ✅ |
| **kling-v1-5** | ❌ | ✅ All modes | ❌ | ✅ All modes | ✅ All modes | ✅ All modes | ✅ (simple only) | ✅ |
| **kling-v1-6** | ✅ All modes | ✅ All modes | ✅ All modes | ✅ All modes | ✅ All modes | ✅ All modes | ❌ | ❌ |
| **kling-v2-master** | ✅ (5s, 10s only) | ✅ (5s, 10s only) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **kling-v2-1** | ✅ (5s, 10s only) | ✅ (5s, 10s only) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

**Key Insights:**
- **kling-v2 models**: Only support basic video generation (no mode parameter, no advanced features)
- **kling-v1-5**: No text-to-video support, but has all advanced features for image-to-video
- **kling-v1-6**: Most comprehensive feature support including multi-image video
- **Duration constraints**: v2 models support 5s and 10s only (no pro/std distinction)

### New Model Support
- **kling-v2-master & kling-v2-1**: New v2 models for both text-to-video and image-to-video
- **Multi-Image to Video**: Support for up to 4 input images (kling-v1-6 only)
- **Custom Aspect Ratios**: 16:9, 9:16, 1:1 for v2 models

### New Capabilities
1. **Text to Image Generation**: kling-v1, kling-v1-5 & kling-v2 text-to-image
2. **Image to Image Generation**: Use the same kling-v1, kling-v1-5 models with image reference features to generate image from existing images, plus prompts. kling-v1 supports entire image only. kling-v1-5 supports subject and face references.
3. **Virtual Try-On**: AI-powered clothing try-on with the kolors-virtual-try-on-v1 model
4. **Multi-Image Video**: Generate videos from multiple input images with the kling-v1-6 model
5. **Video Effects**: Creative effects (hug, kiss, heart_gesture, bloom, dizzy, fuzzy, squish, expansion)
6. **Enhanced Image-to-Video**: V2 model support
7. **Video Extension**: Continue videos for additional 4-5 seconds
8. **Lip-sync**: Add lip-sync to generated videos

## Current Node Analysis

### Existing Nodes
1. `text_to_video.py` - Basic text-to-video generation
2. `image_to_video.py` - Image-to-video generation with advanced features

### Missing Functionality
1. Image generation (completely new)
2. Image expansion (completely new)
3. Virtual try-on (completely new)
4. Multi-image video generation
5. Video effects
6. Video extension
7. Lip-sync
8. V2 model optimizations

## Detailed Update Plan

### Phase 1: Core Updates (High Priority)

#### 1.1 Update Base Configuration
- [ ] Update `BASE_URL` constants in all existing nodes
- [ ] Add v2 model validation logic
- [ ] Update model choices in existing nodes

#### 1.2 Create New Text to Video and Image to Video Nodes based on the existing nodes. These new nodes should include the following updates.

##### Text-to-Video Node Updates
- [ ] Add `kling-v2-master` and `kling-v2-1` to model choices
- [ ] Add conditional mode parameter (v2 models don't support mode)
- [ ] Add conditional camera control (v2 models don't support camera control)
- [ ] Add aspect ratio parameter for v2 models (16:9, 9:16, 1:1 only)
- [ ] Update validation logic for model-specific constraints
- [ ] Add model-specific parameter visibility logic
- [ ] Remove duration/mode restrictions for v2 models (only 5s/10s, no std/pro)

##### Image-to-Video Node Updates  
- [ ] Add `kling-v2-master` and `kling-v2-1` to model choices
- [ ] Add conditional mode parameter handling (v2 doesn't support)
- [ ] Add conditional camera control handling (v2 doesn't support)
- [ ] Add conditional motion brush handling (v2 doesn't support)
- [ ] Update aspect ratio support for v2 (16:9, 9:16, 1:1 only)
- [ ] Add v2-specific validation rules
- [ ] Update model capability validation matrix
- [ ] Correct all parameter names to match API exactly
- [ ] Add static_mask and dynamic_masks parameters
- [ ] Add comprehensive camera control parameters with proper validation
- [ ] Add image_tail parameter for end frame control

### Phase 2: New Node Development (High Priority)

#### 2.1 Create Text to Image Generation Node
**File**: `text_to_image.py`
**Documentation**: https://app.klingai.com/global/dev/document-api/apiReference/model/imageGeneration

```python
# API Endpoint: /v1/images/generations
# Key Parameters:
# - prompt (str): Text description (max 2500 chars)
# - model_name (str): kling-v1-5, kling-v2-master, kling-v2-1
# - negative_prompt (str): Optional negative prompt (max 2500 chars)
# - n (int): Number of images to generate (1-8)
# - aspect_ratio (str): 16:9, 9:16, 1:1, 4:3, 3:4, 3:2, 2:3, 21:9
# - callback_url (str): Optional callback URL
# - external_task_id (str): Optional custom task ID
```

- [ ] Create base node structure inheriting from `ControlNode`
- [ ] Add all image generation parameters with proper validation
- [ ] Add support for generating multiple images (n=1-8)
- [ ] Add comprehensive aspect ratio support (8 options)
- [ ] Add proper image artifact output (handle multiple images)
- [ ] Implement polling logic for image generation
- [ ] Add comprehensive validation for model-specific features

#### 2.2 Create Image to Image Generation Node
**File**: `image_to_image.py`
**Documentation**: https://app.klingai.com/global/dev/document-api/apiReference/model/imageGeneration

```python
# API Endpoint: /v1/images/expansions/background
# Key Parameters:
# - image (ImageArtifact): Optional reference image
# - prompt (str): Required positive text prompt
# - negative_prompt (str): Optional negative text prompt
# - image_ref_type (str): Optional image reference type. Required when using the kling-v1-5 model if a reference image is provided. Must be set to either subject or face. 
# - image_fidelity (float): Optional reference intensity. Value range 0 to 1. Default value 0.5
# - human_fidelity (float): Optional facial reference intensity. Value range 0 to 1. Default value 0.5
# - n (int): Optional number of generated images. Value range 1 to 9. Default value 1
# - aspect_ratio (str): Optional aspect ratio of the generated images. Options (16:9, 9:16, 1:1, 4:3, 3:4, 3:2, 2:3, 21:9). Default 1:1.
# - external_task_id (str): Optional custom task ID
```

- [ ] Create base node structure inheriting from `ControlNode`
- [ ] Add image input parameter with proper validation
- [ ] Add text input parameters for prompt, negative_prompt, with input connections 
- [ ] Add slider parameters for image_fidelity, human_fidelity, with the correct defaults of 0.5
- [ ] Add slider parameter for n with the correct default of 1
- [ ] Add dropdown list parameter for aspect_ratio with the default of 1:1
- [ ] Implement proper image artifact output
- [ ] Add expansion preview/visualization helpers if possible
- [ ] Implement polling logic for image expansion
- [ ] Add validation to ensure at least one expansion ratio > 0

#### 2.3 Create Virtual Try-On Node
**File**: `virtual_try_on.py`
**Documentation**: https://app.klingai.com/global/dev/document-api/apiReference/model/functionalityTry

```python
# API Endpoint: /v1/images/kolors-virtual-try-on
# Key Parameters:
# - model_name (str): Optional, default "kolors-virtual-try-on-v1"
#   Enum values: "kolors-virtual-try-on-v1", "kolors-virtual-try-on-v1-5"
# - human_img (str): Required - Reference human image (Base64 or URL)
#   Supported formats: jpg/jpeg/png
#   Size constraints: max 1024px width/height, min 300px
# - cloth_img (str): Optional - Reference clothing image (Base64 or URL)
#   Supported formats: jpg/jpeg/png  
#   Size constraints: max 1024px width/height, min 300px
#   Special combinations supported for v1-5:
#     - "upper" + "lower" -> Generate try-on result
#     - "dress" + "dress" -> Generate try-on result
#     - Other combinations possible
# - callback_url (str): Optional callback URL
```

- [ ] Create base node structure inheriting from `ControlNode`
- [ ] Add model_name parameter with Options trait (v1, v1-5)
- [ ] Add human_img input parameter with proper validation
- [ ] Add cloth_img input parameter with proper validation
- [ ] Add image size validation (300px-1024px constraints)
- [ ] Add image format validation (jpg/jpeg/png only)
- [ ] Implement model-specific combination validation for v1-5
- [ ] Add proper image artifact output
- [ ] Implement polling logic for try-on completion
- [ ] Add comprehensive validation for clothing/human image compatibility

#### 2.4 Create new v2 Existing Image-to-Video Node
**File**: `image_to_video.py` (Update existing)
**Documentation**: https://app.klingai.com/global/dev/document-api/apiReference/model/imageToVideo

```python
# API Endpoint: /v1/videos/image2video  
# Correct Parameter Names from API:
# - model_name (str): kling-v1, kling-v1-5, kling-v1-6, kling-v2-master
# - image (str): Reference image (Base64 or URL)
# - image_tail (str): End frame control image (Base64 or URL)
# - prompt (str): Positive text prompt (max 2500 chars)
# - negative_prompt (str): Negative text prompt (max 2500 chars)
# - cfg_scale (float): Flexibility 0-1 (default 0.5)
# - mode (str): std/pro (not supported on v2 models)
# - static_mask (str): Static brush application area
# - dynamic_masks (str): Dynamic brush configuration (JSON format)
# - camera_control (object): Camera movement configuration
#   - type (str): simple, down_back, forward_up, right_turn_forward, left_turn_forward
#   - config (object): For "simple" type, camera movement parameters
# - duration (str): Video length "5" or "10" seconds
# - callback_url (str): Optional callback URL  
# - external_task_id (str): Optional custom task ID
```

- [ ] Update existing node to match exact API parameter names
- [ ] Add image_tail parameter for end frame control
- [ ] Add static_mask parameter for brush application areas
- [ ] Add dynamic_masks parameter for complex brush configurations
- [ ] Update camera_control to proper object structure with type/config
- [ ] Add comprehensive validation for brush vs camera control mutual exclusion
- [ ] Update model-specific feature validation based on capability matrix
- [ ] Add proper JSON validation for dynamic_masks parameter

#### 2.4 Create Multi-Image Video Node
**File**: `multi_image_to_video.py`
**Documentation**: https://app.klingai.com/global/dev/document-api/apiReference/model/multiImageToVideo

```python
# API Endpoint: /v1/videos/multi-images2video
# Key Parameters:
# - model_name (str): Optional, default "kling-v1-6" (ONLY kling-v1-6 supported)
# - image_list (array): Required, up to 4 images with key-value details
# - prompt (str): Required, text description (max 2500 chars)
# - negative_prompt (str): Optional, negative text prompt (max 2500 chars)
# - mode (str): Optional, "std" (Standard Mode, cost-effective) or "pro" (Professional Mode, higher quality)
# - duration (str): Optional, "5" or "10" seconds
# - aspect_ratio (str): Optional, "16:9" (default)
# - callback_url (str): Optional callback URL
# - external_task_id (str): Optional custom task ID
```

- [ ] Create node with ParameterList for multiple images (max 4)
- [ ] Add validation for image count (max 4) with proper error messages
- [ ] Add model restriction validation (only kling-v1-6 supports this)
- [ ] Implement image_list array formatting for API
- [ ] Add mode parameter with std/pro options
- [ ] Add duration parameter with 5s/10s options
- [ ] Add aspect_ratio parameter (16:9 default)
- [ ] Add prompt as required parameter with 2500 char limit
- [ ] Add proper error handling for multi-image scenarios
- [ ] Implement polling logic for video generation

### Phase 3: Advanced Features (Medium Priority)

#### 3.1 Video Effects Node
**File**: `video_effects.py`
**Documentation**: https://app.klingai.com/global/dev/document-api/apiReference/model/videoEffects

```python
# API Endpoint: /v1/videos/effects
# Key Parameters:
# - effect_scene (str): Required - Effect type name
#   Single-image effects: "bloombloom", "dizzydizzy", "fuzzyfuzzy", "squish", "expansion"
#   Dual-character effects: "hug", "kiss", "heart_gesture"
# - input (object): Required - Contains effect configuration
#   For Single-image effects:
#     - model_name (str): Required, "kling-v1-6"
#     - image (str): Required - Reference image (Base64 or URL)
#     - duration (str): Required - "5" seconds only
#   For Dual-character effects:
#     - model_name (str): Optional, default "kling-v1" 
#     - mode (str): Optional, "std" (default)
#     - images (array): Required - 2 images for dual-character effects
#       First image: positioned on left side of composite
#       Second image: positioned on right side of composite
#     - duration (str): Required - "5" seconds only
# - callback_url (str): Optional callback URL
# - external_task_id (str): Optional custom task ID
```

- [ ] Create base video effects node structure with nested input object
- [ ] Add effect_scene parameter with Options trait for all effect types
- [ ] Implement conditional input structure based on effect type
- [ ] Add single-image input mode (1 image) for bloom, dizzy, fuzzy, squish, expansion
- [ ] Add dual-character input mode (2 images) for hug, kiss, heart_gesture
- [ ] Add model_name parameter with conditional defaults (v1-6 for single, v1 for dual)
- [ ] Add mode parameter for dual-character effects only
- [ ] Add duration parameter (fixed to "5" seconds for all effects)
- [ ] Implement automatic image positioning logic for dual-character effects
- [ ] Add comprehensive validation for effect-specific requirements
- [ ] Add proper video output handling
- [ ] Implement polling logic for effect completion

#### 3.2 Video Extension Node
**File**: `video_extension.py`
**Documentation**: https://app.klingai.com/global/dev/document-api/apiReference/model/videoDuration

```python
# API Endpoint: /v1/videos/video-extend
# Key Parameters:
# - video_id (str): Required - Video ID from previous Kling AI generation
# - prompt (str): Optional, text prompt (max 2500 chars)
# - negative_prompt (str): Optional, negative text prompt (max 2500 chars)
# - cfg_scale (float): Optional, flexibility 0-1 (default 0.5)
# - callback_url (str): Optional callback URL
# 
# Important Notes:
# - Each extension adds 4-5 seconds to video duration
# - Only supported for videos generated by V1.5 model
# - Videos can be extended multiple times (max total duration: 3 minutes)
# - Cannot select model - uses same model as source video
```

- [ ] Create node for extending existing Kling AI videos
- [ ] Add video_id input parameter with proper validation
- [ ] Add optional prompt parameter for guided extension
- [ ] Add negative_prompt parameter
- [ ] Add cfg_scale parameter with 0-1 range validation
- [ ] Implement model compatibility checking (V1.5 only)
- [ ] Add duration limit validation (max 3 minutes total)
- [ ] Handle video ID extraction and API calls
- [ ] Add proper video artifact chaining
- [ ] Implement polling logic for extension completion

#### 3.3 Lip-Sync Node  
**File**: `lip_sync.py`
**Documentation**: https://app.klingai.com/global/dev/document-api/apiReference/model/videoTolip

```python
# API Endpoint: /v1/videos/lip-sync
# Key Parameters:
# - input (object): Required - Contains lip-sync configuration
#   - video_id (str): Optional - ID of video generated by Kling AI
#   - mode (str): Required - "lipSynVideo" or "audioVideo"
#   - text (str): Optional - Text content for lip-sync (max 120 chars)
#   - voice_id (str): Optional - Voice ID for lipSynVideo mode
#   - voice_language (str): Optional - "zh" or "en"
#   - voice_speed (float): Optional - Speech rate 0.5-2.0 (default 1.0)
#   - audio_type (str): Optional - "file" or "url"
#   - audio_file: Optional - Upload audio file
#   - audio_url (str): Optional - Audio file download URL
# - callback_url (str): Optional callback URL
```

- [ ] Create lip-sync node structure with nested input object
- [ ] Add video_id input parameter for Kling AI videos
- [ ] Add mode parameter with "lipSynVideo"/"audioVideo" options
- [ ] Add text input parameter with 120 char limit
- [ ] Add voice_id parameter for voice selection
- [ ] Add voice_language parameter (zh/en options)
- [ ] Add voice_speed parameter with 0.5-2.0 range validation
- [ ] Add audio_type parameter for file vs URL input
- [ ] Add audio_file parameter for direct upload
- [ ] Add audio_url parameter for URL-based audio
- [ ] Implement mode-specific parameter visibility
- [ ] Add comprehensive validation for different input modes
- [ ] Implement polling logic for lip-sync completion

### Phase 4: Enhanced UX and Optimization (Low Priority)

#### 4.1 Parameter Grouping and UI Improvements
- [ ] Add ParameterGroup containers for related settings
- [ ] Implement conditional parameter visibility based on model selection
- [ ] Add progressive disclosure for advanced features
- [ ] Implement better tooltips with model-specific guidance
- [ ] Add parameter validation with helpful error messages

#### 4.2 Shared Components and Utilities
- [ ] Create shared `KlingModelParameter` helper class
- [ ] Implement `KlingVideoOutputParameter` for consistent video outputs
- [ ] Add `KlingImageParameter` for image input standardization
- [ ] Create validation utilities for model-specific constraints
- [ ] Add shared API client with retry logic

#### 4.3 Advanced Features Integration
- [ ] Add camera control support for v2 models (when available)
- [ ] Implement motion brush compatibility
- [ ] Add start/end frame control for supported models
- [ ] Create workflow templates for common use cases

## Implementation Guidelines

### Following Node Development Best Practices

#### Parameter Design (from node-development-guide.md)
```python
# Use ParameterGroup for related settings
with ParameterGroup(name="Model Settings") as model_group:
    Parameter(name="model_name", ...)
    Parameter(name="mode", ...)
    Parameter(name="cfg_scale", ...)
model_group.ui_options = {"hide": False}
self.add_node_element(model_group)

# Use Options trait for choices
Parameter(
    name="model_name",
    traits={Options(choices=["kling-v1", "kling-v1-5", "kling-v1-6", "kling-v2-master", "kling-v2-1"])},
    tooltip="Select the Kling model version"
)
```

#### Dynamic Parameter Updates
```python
def after_value_set(self, parameter, value, modified_parameters_set):
    """Update parameter visibility based on model selection."""
    if parameter.name == "model_name":
        if value in ["kling-v2-master", "kling-v2-1"]:
            # Hide mode parameter for v2 models
            self.hide_parameter_by_name("mode")
            # Show aspect ratio for v2
            self.show_parameter_by_name("aspect_ratio")
        else:
            self.show_parameter_by_name("mode")
        modified_parameters_set.add("mode")
        modified_parameters_set.add("aspect_ratio")
        return super().after_value_set(parameter, value, modified_parameters_set)
```

#### Environment Variable Pattern
```python
SERVICE = "Kling"
API_KEY_ENV_VAR = "KLING_ACCESS_KEY"
SECRET_KEY_ENV_VAR = "KLING_SECRET_KEY"
BASE_URL = "https://api-singapore.klingai.com/v1"

def _get_api_credentials(self) -> tuple[str, str]:
    access_key = self.get_config_value(service=SERVICE, value=API_KEY_ENV_VAR)
    secret_key = self.get_config_value(service=SERVICE, value=SECRET_KEY_ENV_VAR)
    if not access_key or not secret_key:
        raise ValueError(f"Kling credentials not found. Set {API_KEY_ENV_VAR} and {SECRET_KEY_ENV_VAR}")
    return access_key, secret_key
```

### Validation Strategy
```python
def validate_node(self) -> list[Exception] | None:
    errors = []
    
    # Check API credentials
    try:
        self._get_api_credentials()
    except ValueError as e:
        errors.append(e)
    
    # Model-specific validation matrix
    model = self.get_parameter_value("model_name")
    mode = self.get_parameter_value("mode")
    camera_control = self.get_parameter_value("camera_control_type")
    
    # V2 models constraints
    if model in ["kling-v2-master", "kling-v2-1"]:
        if mode and mode != "(Auto)":
            errors.append(ValueError("kling-v2 models do not support mode parameter"))
        if camera_control and camera_control != "(Auto)":
            errors.append(ValueError("kling-v2 models do not support camera control"))
            
    # V1-5 text-to-video restriction  
    if model == "kling-v1-5" and self.__class__.__name__ == "KlingAI_TextToVideo":
        errors.append(ValueError("kling-v1-5 does not support text-to-video generation"))
        
    # Multi-image video restriction
    if self.__class__.__name__ == "KlingAI_MultiImageVideo" and model != "kling-v1-6":
        errors.append(ValueError("Multi-image video only supported on kling-v1-6"))
    
    return errors if errors else None
``` 